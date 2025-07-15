import fitz  # PyMuPDF
import os
import json
import re
from pathlib import Path
from collections import Counter
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PDFOutlineExtractor:
    def __init__(self):
        self.font_size_threshold = 2.0  # Minimum font size difference for heading levels
        self.min_heading_chars = 3  # Minimum characters for a valid heading
        self.max_heading_chars = 200  # Maximum characters for a valid heading
        
    def is_likely_heading(self, text, font_size, is_bold, position_y, page_width):
        """Enhanced heading detection using multiple signals"""
        text = text.strip()
        
        # Basic text validation
        if len(text) < self.min_heading_chars or len(text) > self.max_heading_chars:
            return False
            
        # Skip if mostly numbers or special characters
        if re.match(r'^[\d\s\-\.\(\)]+$', text):
            return False
            
        # Skip common footer/header patterns
        footer_patterns = [
            r'^\d+$',  # Just page numbers
            r'^page\s+\d+',  # "Page 1", "Page 2", etc.
            r'^\d+\s+of\s+\d+$',  # "1 of 10"
            r'^www\.',  # URLs
            r'@',  # Email addresses
            r'^\d{4}$',  # Years
        ]
        
        for pattern in footer_patterns:
            if re.search(pattern, text.lower()):
                return False
        
        # Boost score for heading-like patterns
        heading_patterns = [
            r'^chapter\s+\d+',
            r'^section\s+\d+',
            r'^\d+\.\s+\w+',  # "1. Introduction"
            r'^\d+\.\d+\s+\w+',  # "1.1 Overview"
            r'^[A-Z][a-z]+\s+[A-Z]',  # Title case
        ]
        
        pattern_bonus = any(re.search(pattern, text, re.IGNORECASE) for pattern in heading_patterns)
        
        # Check if text is likely a heading based on position and formatting
        is_left_aligned = position_y is not None  # Simple position check
        
        return (font_size > 10 or is_bold or pattern_bonus) and is_left_aligned
    
    def extract_title_from_metadata(self, doc):
        """Try to extract title from PDF metadata"""
        try:
            metadata = doc.metadata
            if metadata and 'title' in metadata and metadata['title']:
                return metadata['title'].strip()
        except:
            pass
        return None
    
    def extract_title_from_first_page(self, doc):
        """Extract title from first page using heuristics"""
        if len(doc) == 0:
            return None
            
        page = doc[0]
        blocks = page.get_text("dict")["blocks"]
        
        candidates = []
        
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                line_text = ""
                max_font = 0
                is_bold = False
                bbox = line.get("bbox", [0, 0, 0, 0])
                
                for span in line["spans"]:
                    if span["text"].strip():
                        line_text += span["text"].strip() + " "
                        max_font = max(max_font, span["size"])
                        if span["flags"] & 2**4:  # Bold flag
                            is_bold = True
                
                line_text = line_text.strip()
                if line_text and len(line_text) > 5:
                    # Title candidates are usually near the top, large font, or bold
                    y_position = bbox[1] if bbox else 0
                    score = max_font + (20 if is_bold else 0) + (100 if y_position < 200 else 0)
                    candidates.append((score, line_text, y_position))
        
        if candidates:
            # Sort by score and return the best candidate
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        
        return None
    
    def extract_outline(self, pdf_path):
        """Extract structured outline from PDF"""
        try:
            doc = fitz.open(pdf_path)
            
            # Try to get title from metadata first
            title = self.extract_title_from_metadata(doc)
            if not title:
                title = self.extract_title_from_first_page(doc)
            
            font_data = []
            
            # Extract all text with formatting information
            for page_index in range(len(doc)):
                page = doc[page_index]
                blocks = page.get_text("dict")["blocks"]
                page_rect = page.rect
                
                for block in blocks:
                    if "lines" not in block:
                        continue
                    for line in block["lines"]:
                        line_text = ""
                        max_font = 0
                        is_bold = False
                        bbox = line.get("bbox", [0, 0, 0, 0])
                        
                        for span in line["spans"]:
                            if span["text"].strip():
                                line_text += span["text"].strip() + " "
                                max_font = max(max_font, span["size"])
                                # Check for bold formatting
                                if span["flags"] & 2**4:  # Bold flag
                                    is_bold = True
                        
                        line_text = line_text.strip()
                        if line_text:
                            y_position = bbox[1] if bbox else 0
                            page_width = page_rect.width
                            
                            # Check if this looks like a heading
                            if self.is_likely_heading(line_text, max_font, is_bold, y_position, page_width):
                                font_data.append({
                                    'size': max_font,
                                    'text': line_text,
                                    'page': page_index + 1,
                                    'is_bold': is_bold,
                                    'y_position': y_position
                                })
            
            doc.close()
            
            # If no font data found, return empty structure
            if not font_data:
                return {
                    "title": title or "Untitled Document",
                    "outline": []
                }
            
            # Determine heading levels using multiple criteria
            outline = self.determine_heading_levels(font_data, title)
            
            return {
                "title": title or (outline[0]["text"] if outline else "Untitled Document"),
                "outline": outline
            }
            
        except Exception as e:
            logger.error(f"Error processing {pdf_path}: {str(e)}")
            return {
                "title": "Error Processing Document",
                "outline": []
            }
    
    def determine_heading_levels(self, font_data, title):
        """Determine heading levels using font size, bold, and position"""
        if not font_data:
            return []
        
        # Sort by page, then by y_position (top to bottom)
        font_data.sort(key=lambda x: (x['page'], -x['y_position']))
        
        # Collect all font sizes and their frequencies
        font_sizes = [item['size'] for item in font_data]
        size_counts = Counter(font_sizes)
        
        # Get unique font sizes, prioritizing larger sizes and bold text
        unique_items = []
        seen_combinations = set()
        
        for item in font_data:
            key = (item['size'], item['is_bold'])
            if key not in seen_combinations:
                unique_items.append(item)
                seen_combinations.add(key)
        
        # Sort by size (desc) and bold status
        unique_items.sort(key=lambda x: (x['size'], x['is_bold']), reverse=True)
        
        # Assign levels to top 3 unique combinations
        level_mapping = {}
        level_names = ["H1", "H2", "H3"]
        
        for i, item in enumerate(unique_items[:3]):
            key = (item['size'], item['is_bold'])
            if key not in level_mapping:
                level_mapping[key] = level_names[i]
        
        # Build outline
        outline = []
        for item in font_data:
            key = (item['size'], item['is_bold'])
            level = level_mapping.get(key)
            
            if level:
                # Skip if this text is the same as the title
                if title and item['text'].strip().lower() == title.strip().lower():
                    continue
                    
                outline.append({
                    "level": level,
                    "text": item['text'],
                    "page": item['page']
                })
        
        # Remove duplicates while preserving order
        seen_texts = set()
        filtered_outline = []
        for item in outline:
            text_key = (item['text'].lower(), item['page'])
            if text_key not in seen_texts:
                seen_texts.add(text_key)
                filtered_outline.append(item)
        
        return filtered_outline

def process_pdfs():
    """Main processing function"""
    input_dir = Path("/app/input")
    output_dir = Path("/app/output")
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not input_dir.exists():
        logger.error(f"Input directory {input_dir} does not exist")
        return
    
    # Find all PDF files
    pdf_files = list(input_dir.glob("*.pdf"))
    
    if not pdf_files:
        logger.warning(f"No PDF files found in {input_dir}")
        return
    
    logger.info(f"Found {len(pdf_files)} PDF files to process")
    
    extractor = PDFOutlineExtractor()
    
    for pdf_file in pdf_files:
        try:
            logger.info(f"Processing: {pdf_file.name}")
            result = extractor.extract_outline(pdf_file)
            
            output_file = output_dir / f"{pdf_file.stem}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            logger.info(f" Processed: {pdf_file.name} -> {output_file.name}")
            logger.info(f"   Title: {result['title']}")
            logger.info(f"   Outline entries: {len(result['outline'])}")
            
        except Exception as e:
            logger.error(f" Failed to process {pdf_file.name}: {str(e)}")
            
            # Create error output file
            error_result = {
                "title": f"Error: {pdf_file.name}",
                "outline": []
            }
            output_file = output_dir / f"{pdf_file.stem}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(error_result, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    process_pdfs()
