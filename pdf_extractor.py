#!/usr/bin/env python3
"""
PDF Outline Extractor - Highlights Only
Extracts only key highlights, headings, and titles from PDF documents.
Filters out sentences and paragraphs to focus on structural elements.
"""

import os
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
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
        # More conservative font size thresholds
        self.font_size_thresholds = {
            'title': 20,
            'h1': 18,
            'h2': 16,
            'h3': 14
        }
        
        # Common words that indicate this is regular text, not a heading
        self.common_sentence_indicators = {
            'the', 'and', 'that', 'this', 'with', 'from', 'for', 'was', 'are', 'have', 'has', 
            'but', 'also', 'which', 'their', 'there', 'they', 'will', 'would', 'could', 'should',
            'been', 'being', 'does', 'did', 'can', 'may', 'might', 'must', 'shall', 'through',
            'during', 'before', 'after', 'above', 'below', 'between', 'among', 'within', 'without'
        }

    def extract_text_with_formatting(self, pdf_path: str) -> List[Dict]:
        text_blocks = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    if page.chars:
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
            if 'fontname' in char and ('bold' in char['fontname'].lower() or 'black' in char['fontname'].lower()):
                lines[y_pos]['is_bold'] = True
        
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
        text_blocks = []
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PdfReader(file)
                for page_num, page in enumerate(pdf_reader.pages, 1):
                    text = page.extract_text()
                    if text:
                        lines = text.splitlines()
                        for line in lines:
                            if line.strip():
                                text_blocks.append({
                                    'text': line.strip(),
                                    'page': page_num,
                                    'font_size': 12,
                                    'is_bold': False,
                                    'y_position': 0
                                })
        except Exception as e:
            logger.error(f"Fallback extraction failed: {e}")
        return text_blocks

    def extract_title(self, text_blocks: List[Dict]) -> str:
        """Extract document title from first few blocks"""
        for block in text_blocks[:10]:
            text = block['text'].strip()
            if not text or re.match(r'^\d+$', text):
                continue
            
            # Title should be prominent and not a sentence
            if (len(text) > 5 and len(text) < 80 and
                not self._is_sentence(text) and
                (block['font_size'] >= self.font_size_thresholds['title'] or
                 block['is_bold'] or text.isupper())):
                return text
        
        # Fallback to first non-empty block
        for block in text_blocks[:5]:
            if block['text'].strip():
                return block['text'].strip()
        
        return "Untitled Document"

    def _is_sentence(self, text: str) -> bool:
        """Determine if text is a sentence rather than a heading/highlight"""
        text = text.strip()
        
        # Check for sentence endings
        if text.endswith(('.', '!', '?', ';', ':')):
            return True
        
        # Check for multiple punctuation marks (indicates prose)
        punctuation_count = len(re.findall(r'[.!?,;:]', text))
        if punctuation_count >= 2:
            return True
        
        # Check for common sentence patterns
        if re.search(r'\b(is|are|was|were|has|have|had|will|would|could|should)\b', text.lower()):
            return True
        
        # Check for articles and prepositions that indicate sentences
        words = text.lower().split()
        if len(words) > 1:
            common_word_count = sum(1 for word in words if word in self.common_sentence_indicators)
            # If more than 30% of words are common sentence indicators, it's likely a sentence
            if common_word_count / len(words) > 0.3:
                return True
        
        # Check for parenthetical expressions
        if '(' in text and ')' in text:
            return True
        
        return False

    def _is_valid_heading(self, text: str) -> bool:
        """Check if text could be a valid heading/highlight"""
        text = text.strip()
        
        # Basic length constraints
        if len(text) < 2 or len(text) > 100:
            return False
        
        # Skip if it's clearly a sentence
        if self._is_sentence(text):
            return False
        
        # Skip if all lowercase (usually not a heading)
        if text.islower():
            return False
        
        # Skip if too many words (likely a sentence)
        if len(text.split()) > 10:
            return False
        
        # Skip page numbers and references
        if re.match(r'^\d+$', text) or re.match(r'^Page\s+\d+', text, re.IGNORECASE):
            return False
        
        # Skip common footer/header elements
        footer_patterns = [
            r'^\d{1,2}/\d{1,2}/\d{2,4}$',  # dates
            r'^www\.',  # websites
            r'@.*\.com',  # emails
            r'^\d+\s*$',  # page numbers
            r'^(page|p\.)\s*\d+',  # page indicators
        ]
        
        for pattern in footer_patterns:
            if re.match(pattern, text, re.IGNORECASE):
                return False
        
        return True

    def classify_heading_level(self, text: str, font_size: float, is_bold: bool, context: Dict) -> Optional[str]:
        """Classify heading level based on formatting and content"""
        if not self._is_valid_heading(text):
            return None
        
        text = text.strip()
        avg_font_size = context.get('avg_font_size', 12)
        
        # Strong heading patterns get priority
        strong_patterns = [
            r'^(Chapter|CHAPTER|Section|SECTION|Part|PART)\s+\d+',
            r'^\d+(\.\d+)*\s+[A-Z]',  # Numbered headings
            r'^[A-Z][A-Z\s]{4,}$',    # ALL CAPS headings
            r'^[IVX]+\.\s+[A-Z]',     # Roman numerals
            r'^[A-Z]\.\s+[A-Z]',      # Letter outlines
        ]
        
        for pattern in strong_patterns:
            if re.match(pattern, text):
                if font_size >= self.font_size_thresholds['h1'] or is_bold:
                    return "H1"
                else:
                    return "H2"
        
        # Font size based classification
        if font_size >= self.font_size_thresholds['h1']:
            return "H1"
        elif font_size >= self.font_size_thresholds['h2']:
            return "H2"
        elif font_size >= self.font_size_thresholds['h3']:
            return "H3"
        
        # Bold text with reasonable size
        if is_bold and font_size > avg_font_size * 1.1:
            if font_size > avg_font_size * 1.3:
                return "H2"
            else:
                return "H3"
        
        # Large font size relative to average
        if font_size > avg_font_size * 1.5:
            return "H2"
        elif font_size > avg_font_size * 1.2:
            return "H3"
        
        return None

    def extract_outline(self, pdf_path: str) -> Dict:
        """Extract outline containing only highlights and headings"""
        logger.info(f"Processing PDF: {pdf_path}")
        text_blocks = self.extract_text_with_formatting(pdf_path)
        
        if not text_blocks:
            logger.warning(f"No text extracted from {pdf_path}")
            return {
                "title": "Untitled Document",
                "outline": []
            }

        # Calculate font statistics
        font_sizes = [block['font_size'] for block in text_blocks if block['font_size'] > 0]
        avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 12
        
        context = {
            'avg_font_size': avg_font_size,
            'total_blocks': len(text_blocks)
        }

        title = self.extract_title(text_blocks)
        outline = []
        seen_headings = set()

        for block in text_blocks:
            text = block['text'].strip()
            
            # Skip duplicates and very short text
            if text in seen_headings or len(text) < 2:
                continue
            
            level = self.classify_heading_level(
                text,
                block['font_size'],
                block['is_bold'],
                context
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
        """Process all PDF files in input directory"""
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        pdf_files = list(input_path.glob("*.pdf"))

        if not pdf_files:
            logger.warning(f"No PDF files found in {input_dir}")
            return

        logger.info(f"Found {len(pdf_files)} PDF files to process")
        
        for pdf_file in pdf_files:
            try:
                outline_data = self.extract_outline(str(pdf_file))
                output_file = output_path / f"{pdf_file.stem}.json"
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(outline_data, f, ensure_ascii=False, indent=2)
                
                logger.info(f"Processed {pdf_file.name} -> {output_file.name}")
                
            except Exception as e:
                logger.error(f"Error processing {pdf_file.name}: {e}")
                error_output = {
                    "title": f"Error processing {pdf_file.name}",
                    "outline": []
                }
                output_file = output_path / f"{pdf_file.stem}.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(error_output, f, ensure_ascii=False, indent=2)


def main():
    input_dir = "/app/input"
    output_dir = "/app/output"
    
    if not os.path.exists(input_dir):
        logger.error(f"Input directory {input_dir} does not exist")
        sys.exit(1)
    
    os.makedirs(output_dir, exist_ok=True)
    
    extractor = PDFOutlineExtractor()
    extractor.process_directory(input_dir, output_dir)
    
    logger.info("PDF outline extraction completed")


if __name__ == "__main__":
    main()