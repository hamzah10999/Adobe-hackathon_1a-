# Required imports
import fitz  # PyMuPDF for reading and analyzing PDFs
import os
import json
import re
import time
from pathlib import Path
from collections import Counter
import logging

# Configure logging for clean console output
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Main class for heading extraction
class PDFOutlineExtractor:
    def __init__(self):
        self.font_size_threshold = 2.0  # Minimum font size difference between heading levels
        self.min_heading_chars = 3      # Ignore headings with very short text
        self.max_heading_chars = 200    # Ignore headings with unusually long text

    def is_likely_heading(self, text, font_size, is_bold, position_y, page_width):
        """
        Determines whether a text line looks like a heading using:
        - font size
        - boldness
        - regex patterns
        - vertical position (e.g. top of page)
        """
        text = text.strip()

        # Ignore very short or long text
        if len(text) < self.min_heading_chars or len(text) > self.max_heading_chars:
            return False

        # Ignore lines that are just numbers/symbols (e.g., page numbers)
        if re.match(r'^[\d\s\-\.\(\)]+$', text):
            return False

        # Common footer/header patterns to skip
        footer_patterns = [
            r'^\d+$',
            r'^page\s+\d+',
            r'^\d+\s+of\s+\d+$',
            r'^www\.',
            r'@',
            r'^\d{4}$',
        ]
        for pattern in footer_patterns:
            if re.search(pattern, text.lower()):
                return False

        # Regex patterns that increase likelihood of a heading
        heading_patterns = [
            r'^chapter\s+\d+',
            r'^section\s+\d+',
            r'^\d+\.\s+\w+',
            r'^\d+\.\d+\s+\w+',
            r'^[A-Z][a-z]+\s+[A-Z]',
        ]
        pattern_bonus = any(re.search(pattern, text, re.IGNORECASE) for pattern in heading_patterns)

        # Ensure we have position data
        is_left_aligned = position_y is not None

        # Return True if it's visually or semantically likely to be a heading
        return (font_size > 10 or is_bold or pattern_bonus) and is_left_aligned

    def extract_title_from_metadata(self, doc):
        """Try extracting document title from PDF metadata."""
        try:
            metadata = doc.metadata
            if metadata and 'title' in metadata and metadata['title']:
                return metadata['title'].strip()
        except:
            pass
        return None

    def extract_title_from_first_page(self, doc):
        """Extracts the title from the first page based on font size and boldness."""
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
                        if span["flags"] & 2**4:
                            is_bold = True

                line_text = line_text.strip()
                if line_text and len(line_text) > 5:
                    y_position = bbox[1] if bbox else 0
                    score = max_font + (20 if is_bold else 0) + (100 if y_position < 200 else 0)
                    candidates.append((score, line_text, y_position))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        return None

    def extract_outline(self, pdf_path):
        """Extracts the document outline: title + headings with level and page."""
        try:
            doc = fitz.open(pdf_path)

            # Extract title from metadata or heuristically from first page
            title = self.extract_title_from_metadata(doc)
            if not title:
                title = self.extract_title_from_first_page(doc)

            font_data = []

            # Loop through each page to gather candidate headings
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
                                if span["flags"] & 2**4:
                                    is_bold = True

                        line_text = line_text.strip()
                        if line_text:
                            y_position = bbox[1] if bbox else 0
                            page_width = page_rect.width

                            if self.is_likely_heading(line_text, max_font, is_bold, y_position, page_width):
                                font_data.append({
                                    'size': max_font,
                                    'text': line_text,
                                    'page': page_index + 1,
                                    'is_bold': is_bold,
                                    'y_position': y_position
                                })

            doc.close()

            if not font_data:
                return {
                    "title": title or "Untitled Document",
                    "outline": []
                }

            # Determine heading levels like H1, H2, H3
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
        """
        Assign heading levels H1, H2, H3 based on font size, boldness and position.
        """
        if not font_data:
            return []

        # Sort by page number and y-position (top of page first)
        font_data.sort(key=lambda x: (x['page'], -x['y_position']))
        font_sizes = [item['size'] for item in font_data]
        size_counts = Counter(font_sizes)

        unique_items = []
        seen_combinations = set()

        for item in font_data:
            key = (item['size'], item['is_bold'])
            if key not in seen_combinations:
                unique_items.append(item)
                seen_combinations.add(key)

        # Sort by size (desc) and boldness
        unique_items.sort(key=lambda x: (x['size'], x['is_bold']), reverse=True)

        # Map top 3 formats to H1, H2, H3
        level_mapping = {}
        level_names = ["H1", "H2", "H3"]

        for i, item in enumerate(unique_items[:3]):
            key = (item['size'], item['is_bold'])
            if key not in level_mapping:
                level_mapping[key] = level_names[i]

        outline = []
        for item in font_data:
            key = (item['size'], item['is_bold'])
            level = level_mapping.get(key)

            if level:
                # Avoid duplicating title in the outline
                if title and item['text'].strip().lower() == title.strip().lower():
                    continue

                outline.append({
                    "level": level,
                    "text": item['text'],
                    "page": item['page']
                })

        # Remove duplicate headings (same text and page)
        seen_texts = set()
        filtered_outline = []
        for item in outline:
            text_key = (item['text'].lower(), item['page'])
            if text_key not in seen_texts:
                seen_texts.add(text_key)
                filtered_outline.append(item)

        return filtered_outline


# ----------- MAIN PROCESSING SCRIPT BELOW ------------------

def process_pdfs():
    """Scans the input folder and processes all PDFs into structured outline JSONs."""
    input_dir = Path("/app/input")
    output_dir = Path("/app/output")

    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists():
        logger.error(f"Input directory {input_dir} does not exist")
        return

    # Get all PDF files in the input folder
    pdf_files = list(input_dir.glob("*.pdf"))

    if not pdf_files:
        logger.warning(f"No PDF files found in {input_dir}")
        return

    logger.info(f"Found {len(pdf_files)} PDF files to process")
    extractor = PDFOutlineExtractor()

    for pdf_file in pdf_files:
        try:
            logger.info(f"Processing: {pdf_file.name}")
            start_time = time.time()  # ⏱️ Start timing

            result = extractor.extract_outline(pdf_file)

            end_time = time.time()    # ⏱️ End timing
            elapsed = end_time - start_time

            output_file = output_dir / f"{pdf_file.stem}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            logger.info(f" Processed: {pdf_file.name} -> {output_file.name}")
            logger.info(f"   Title: {result['title']}")
            logger.info(f"   Outline entries: {len(result['outline'])}")
            logger.info(f"   ⏱️ Time taken: {elapsed:.2f} seconds")

        except Exception as e:
            logger.error(f" Failed to process {pdf_file.name}: {str(e)}")

            # Write error JSON if processing fails
            error_result = {
                "title": f"Error: {pdf_file.name}",
                "outline": []
            }
            output_file = output_dir / f"{pdf_file.stem}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(error_result, f, ensure_ascii=False, indent=2)

# Entrypoint for the script
if __name__ == "__main__":
    process_pdfs()
