import os
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import logging

try:
    import PyPDF2
    import pdfplumber
    from PyPDF2 import PdfReader
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PDFOutlineExtractor:
    def __init__(self):
        # Common heading patterns for different languages
        self.heading_patterns = {
            'english': [
                r'^(Chapter|CHAPTER)\s+\d+',
                r'^(Section|SECTION)\s+\d+',
                r'^\d+\.\s+',
                r'^\d+\.\d+\s+',
                r'^\d+\.\d+\.\d+\s+',
                r'^[A-Z][A-Z\s]{2,}$',  # ALL CAPS headings
                r'^[A-Z][a-z\s]+:$',    # Title case with colon
            ],
            'multilingual': [
                r'^第\d+章',  # Japanese chapter
                r'^第\d+節',  # Japanese section
                r'^\d+\.?\s*',  # Numbered sections
                r'^[A-Z\u4e00-\u9fff][A-Z\u4e00-\u9fff\s]{2,}$',  # Mixed case with CJK
            ]
        }
        
        # Font size thresholds for heading detection
        self.font_size_thresholds = {
            'title': 16,
            'h1': 14,
            'h2': 12,
            'h3': 10
        }
        
    def extract_text_with_formatting(self, pdf_path: str) -> List[Dict]:
        """Extract text with font information using pdfplumber"""
        text_blocks = []
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    if page.chars:
                        # Group characters by line
                        lines = self._group_chars_by_line(page.chars)
                        
                        for line in lines:
                            if line['text'].strip():
                                text_blocks.append({
                                    'text': line['text'].strip(),
                                    'page': page_num,
                                    'font_size': line['font_size'],
                                    'is_bold': line['is_bold'],
                                    'y_position': line['y_position']
                                })
        except Exception as e:
            logger.error(f"Error extracting formatted text: {e}")
            return self._fallback_text_extraction(pdf_path)
        
        return text_blocks
    
    def _group_chars_by_line(self, chars: List[Dict]) -> List[Dict]:
        """Group characters into lines based on y-position"""
        lines = {}
        
        for char in chars:
            y_pos = round(char['y0'], 1)
            if y_pos not in lines:
                lines[y_pos] = {
                    'chars': [],
                    'font_sizes': [],
                    'is_bold': False,
                    'y_position': y_pos
                }
            
            lines[y_pos]['chars'].append(char['text'])
            lines[y_pos]['font_sizes'].append(char['size'])
            
            # Check if character is bold
            if 'fontname' in char and ('bold' in char['fontname'].lower() or 'black' in char['fontname'].lower()):
                lines[y_pos]['is_bold'] = True
        
        # Convert to list and calculate average font size per line
        result = []
        for y_pos in sorted(lines.keys(), reverse=True):
            line_data = lines[y_pos]
            result.append({
                'text': ''.join(line_data['chars']),
                'font_size': max(line_data['font_sizes']) if line_data['font_sizes'] else 12,
                'is_bold': line_data['is_bold'],
                'y_position': y_pos
            })
        
        return result
    
    def _fallback_text_extraction(self, pdf_path: str) -> List[Dict]:
        """Fallback text extraction using PyPDF2"""
        text_blocks = []
        
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PdfReader(file)
                
                for page_num, page in enumerate(pdf_reader.pages, 1):
                    text = page.extract_text()
                    if text:
                        lines = text.split('\n')
                        for line in lines:
                            if line.strip():
                                text_blocks.append({
                                    'text': line.strip(),
                                    'page': page_num,
                                    'font_size': 12,  # Default font size
                                    'is_bold': False,
                                    'y_position': 0
                                })
        except Exception as e:
            logger.error(f"Fallback extraction failed: {e}")
        
        return text_blocks
    
    def extract_title(self, text_blocks: List[Dict]) -> str:
        """Extract document title from the first few blocks"""
        if not text_blocks:
            return "Untitled Document"
        
        # Look for title in first few blocks
        for block in text_blocks[:10]:
            text = block['text'].strip()
            
            # Skip empty lines and page numbers
            if not text or re.match(r'^\d+$', text):
                continue
            
            # Title characteristics
            if (len(text) > 5 and len(text) < 100 and 
                (block['font_size'] >= self.font_size_thresholds['title'] or
                 block['is_bold'] or
                 text.isupper())):
                return text
        
        # Fallback to first non-empty line
        for block in text_blocks[:5]:
            if block['text'].strip():
                return block['text'].strip()
        
        return "Untitled Document"
    
    def classify_heading_level(self, text: str, font_size: float, is_bold: bool) -> Optional[str]:
        """Classify text as H1, H2, or H3 based on multiple criteria"""
        
        # Skip very short or very long text
        if len(text) < 3 or len(text) > 200:
            return None
        
        # Skip common non-heading patterns
        skip_patterns = [
            r'^\d+$',  # Page numbers
            r'^(page|Page|PAGE)\s+\d+',  # Page indicators
            r'^(table|Table|TABLE)\s+\d+',  # Table captions
            r'^(figure|Figure|FIGURE)\s+\d+',  # Figure captions
            r'^(www\.|http)',  # URLs
            r'^\d{4}-\d{2}-\d{2}',  # Dates
        ]
        
        for pattern in skip_patterns:
            if re.match(pattern, text):
                return None
        
        # Check for heading patterns
        heading_score = 0
        
        # Pattern-based scoring
        for lang_patterns in self.heading_patterns.values():
            for pattern in lang_patterns:
                if re.match(pattern, text):
                    heading_score += 3
                    break
        
        # Font size scoring
        if font_size >= self.font_size_thresholds['h1']:
            heading_score += 2
        elif font_size >= self.font_size_thresholds['h2']:
            heading_score += 1
        
        # Bold text scoring
        if is_bold:
            heading_score += 1
        
        # Structure-based scoring
        if text.isupper() and len(text) > 5:
            heading_score += 2
        
        if re.match(r'^[A-Z][a-z]', text):  # Title case
            heading_score += 1
        
        # Determine level based on score and characteristics
        if heading_score >= 4:
            return 'H1'
        elif heading_score >= 2:
            # Distinguish between H2 and H3
            if font_size >= self.font_size_thresholds['h2'] or re.match(r'^\d+\.\d+\s+', text):
                return 'H2'
            else:
                return 'H3'
        
        return None
    
    def extract_outline(self, pdf_path: str) -> Dict:
        """Extract structured outline from PDF"""
        logger.info(f"Processing PDF: {pdf_path}")
        
        # Extract text with formatting
        text_blocks = self.extract_text_with_formatting(pdf_path)
        
        if not text_blocks:
            logger.warning(f"No text extracted from {pdf_path}")
            return {
                "title": "Untitled Document",
                "outline": []
            }
        
        # Extract title
        title = self.extract_title(text_blocks)
        
        # Extract headings
        outline = []
        seen_headings = set()  # To avoid duplicates
        
        for block in text_blocks:
            text = block['text'].strip()
            
            # Skip if already processed or too short
            if text in seen_headings or len(text) < 3:
                continue
            
            # Classify heading level
            level = self.classify_heading_level(
                text, 
                block['font_size'], 
                block['is_bold']
            )
            
            if level:
                outline.append({
                    "level": level,
                    "text": text,
                    "page": block['page']
                })
                seen_headings.add(text)
        
        logger.info(f"Extracted {len(outline)} headings from {pdf_path}")
        
        return {
            "title": title,
            "outline": outline
        }
    
    def process_directory(self, input_dir: str, output_dir: str) -> None:
        """Process all PDFs in input directory"""
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        # Create output directory if it doesn't exist
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Find all PDF files
        pdf_files = list(input_path.glob("*.pdf"))
        
        if not pdf_files:
            logger.warning(f"No PDF files found in {input_dir}")
            return
        
        logger.info(f"Found {len(pdf_files)} PDF files to process")
        
        for pdf_file in pdf_files:
            try:
                # Extract outline
                outline_data = self.extract_outline(str(pdf_file))
                
                # Save JSON output
                output_file = output_path / f"{pdf_file.stem}.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(outline_data, f, ensure_ascii=False, indent=2)
                
                logger.info(f"Processed {pdf_file.name} -> {output_file.name}")
                
            except Exception as e:
                logger.error(f"Error processing {pdf_file.name}: {e}")
                
                # Create error output
                error_output = {
                    "title": f"Error processing {pdf_file.name}",
                    "outline": []
                }
                
                output_file = output_path / f"{pdf_file.stem}.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(error_output, f, ensure_ascii=False, indent=2)

def main():
    """Main execution function"""
    input_dir = "/app/input"
    output_dir = "/app/output"
    
    # Check if directories exist
    if not os.path.exists(input_dir):
        logger.error(f"Input directory {input_dir} does not exist")
        sys.exit(1)
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize extractor and process files
    extractor = PDFOutlineExtractor()
    extractor.process_directory(input_dir, output_dir)
    
    logger.info("PDF outline extraction completed")

if __name__ == "__main__":
    main()