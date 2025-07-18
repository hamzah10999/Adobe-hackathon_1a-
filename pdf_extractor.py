#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional

try:
    import pdfplumber
except ImportError:
    print("Missing required module: pdfplumber")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PDFOutlineExtractor:
    def __init__(self):
        self.stopwords = {
            'the', 'and', 'that', 'this', 'with', 'from', 'for', 'was', 'are',
            'have', 'has', 'but', 'also', 'which', 'their', 'there', 'they',
            'will', 'would', 'could', 'should', 'been', 'being', 'does', 'did',
            'can', 'may', 'might', 'must', 'shall', 'through', 'during', 'before',
            'after', 'above', 'below', 'between', 'among', 'within', 'without'
        }

    def extract_text_blocks(self, pdf_path: str) -> List[Dict]:
        blocks = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                if not page.chars:
                    continue
                lines = self._group_and_merge_lines(page.chars)
                for line in lines:
                    blocks.append({
                        "text": line["text"],
                        "font_size": line["font_size"],
                        "font_name": line["font_name"],
                        "page": page_num
                    })
        return blocks

    def _group_and_merge_lines(self, chars: List[Dict]) -> List[Dict]:
        grouped = {}
        for char in chars:
            y = round(char['top'], 1)
            if y not in grouped:
                grouped[y] = {"chars": [], "sizes": [], "fonts": []}
            grouped[y]["chars"].append(char.get("text", ""))
            grouped[y]["sizes"].append(char.get("size", 12))
            grouped[y]["fonts"].append(char.get("fontname", ""))

        lines = []
        for y in sorted(grouped.keys()):
            data = grouped[y]
            text = ''.join(data["chars"]).strip()
            if not text:
                continue
            lines.append({
                "text": text,
                "font_size": max(data["sizes"]),
                "font_name": data["fonts"][0] if data["fonts"] else ""
            })

        # Merge multiline headings
        merged = []
        i = 0
        while i < len(lines):
            current = lines[i]
            while (i + 1 < len(lines) and abs(lines[i + 1]['font_size'] - current['font_size']) < 0.5):
                current['text'] += ' ' + lines[i + 1]['text']
                i += 1
            merged.append(current)
            i += 1
        return merged

    def is_valid_heading(self, text: str, font_size: float, avg_font_size: float) -> bool:
        if not text or len(text) < 3 or len(text) > 120:
            return False
        if text.lower() in {"table of contents", "index"}:
            return False
        if len(text.split()) > 16 or text.islower():
            return False
        if re.fullmatch(r'\d{1,2}[-/]\d{1,2}([-/]\d{2,4})?', text):
            return False  # Avoid dates
        if re.fullmatch(r'\d{1,3}$', text.strip()):
            return False  # Avoid lone numbers
        if font_size < avg_font_size * 0.85:
            return False
        if sum(1 for w in text.lower().split() if w in self.stopwords) > 5:
            return False
        if self._has_garbled(text):
            return False
        return True

    def _has_garbled(self, text: str) -> bool:
        # Repeated character groups or gibberish
        return bool(re.search(r'(.)\1{3,}', text)) or bool(re.search(r'\b(\w+)\b\s+\1\b', text, re.IGNORECASE))

    def classify_heading_level(self, font_size: float, ranked_sizes: List[float]) -> Optional[str]:
        try:
            index = ranked_sizes.index(font_size)
            if index < 4:  # Only H1 to H4
                return f"H{index + 1}"
        except ValueError:
            return None
        return None

    def extract_title(self, blocks: List[Dict]) -> str:
        for block in blocks[:10]:
            text = block["text"]
            if self.is_valid_heading(text, block["font_size"], block["font_size"]):
                return text
        return "Untitled Document"

    def is_bold_or_italic(self, font_name: str) -> bool:
        return any(kw in font_name.lower() for kw in ['bold', 'italic', 'oblique', 'underline'])

    def extract_outline(self, pdf_path: str) -> Dict:
        logger.info(f"Processing: {pdf_path}")
        start_time = time.time()
        blocks = self.extract_text_blocks(pdf_path)

        font_sizes = [b["font_size"] for b in blocks]
        avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 12
        ranked_sizes = sorted(set(font_sizes), reverse=True)

        seen = set()
        outline = []

        for block in blocks:
            text = block["text"].strip()
            size = block["font_size"]
            font = block["font_name"]

            if text in seen:
                continue
            if not self.is_valid_heading(text, size, avg_font_size):
                continue
            if not self.is_bold_or_italic(font) and size < avg_font_size * 1.1:
                continue

            level = self.classify_heading_level(size, ranked_sizes)
            if level:
                outline.append({
                    "level": level,
                    "text": text,
                    "page": block["page"]
                })
                seen.add(text)

        duration = round(time.time() - start_time, 2)
        return {
            "title": self.extract_title(blocks),
            "time_taken_seconds": duration,
            "outline": outline
        }

    def process_directory(self, input_dir: str, output_dir: str) -> None:
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        pdfs = list(input_path.glob("*.pdf"))
        if not pdfs:
            logger.warning("No PDFs found.")
            return

        for pdf in pdfs:
            try:
                result = self.extract_outline(str(pdf))
                output_file = output_path / f"{pdf.stem}.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                logger.info(f"Saved: {output_file.name}")
            except Exception as e:
                logger.error(f"Failed to process {pdf.name}: {e}")
                error_output = {
                    "title": f"Error processing {pdf.name}",
                    "time_taken_seconds": 0,
                    "outline": []
                }
                with open(output_path / f"{pdf.stem}.json", "w", encoding="utf-8") as f:
                    json.dump(error_output, f, ensure_ascii=False, indent=2)


def main():
    input_dir = "/app/input"
    output_dir = "/app/output"
    if not os.path.exists(input_dir):
        logger.error(f"Input directory {input_dir} not found.")
        sys.exit(1)

    extractor = PDFOutlineExtractor()
    extractor.process_directory(input_dir, output_dir)
    logger.info("Finished processing all PDFs.")


if __name__ == "__main__":
    main()
