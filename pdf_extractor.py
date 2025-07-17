#!/usr/bin/env python3
import os
import sys
import json
import re
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional

try:
    import pdfplumber
except ImportError as e:
    print(f"Error: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PDFOutlineExtractor:
    def extract_text_with_style(self, pdf_path: str) -> List[Dict]:
        blocks = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                lines = self._group_chars_by_line(page.chars)
                for line in lines:
                    blocks.append({
                        "text": line.get('text', '').strip(),
                        "font_size": line.get('font_size', 12),
                        "font_name": line.get('font_name', ''),
                        "page": page_num
                    })
        return blocks

    def _group_chars_by_line(self, chars: List[Dict]) -> List[Dict]:
        lines = {}
        for char in chars:
            y = round(char['top'], 1)
            if y not in lines:
                lines[y] = {"chars": [], "sizes": [], "fonts": []}
            lines[y]["chars"].append(char.get("text", ""))
            lines[y]["sizes"].append(char.get("size", 12))
            lines[y]["fonts"].append(char.get("fontname", ""))

        result = []
        for y, line in lines.items():
            text = "".join(line["chars"]).strip()
            if not text:
                continue
            font_size = max(line["sizes"]) if line["sizes"] else 12
            font_name = line["fonts"][0] if line["fonts"] else ""
            result.append({
                "text": text,
                "font_size": font_size,
                "font_name": font_name,
                "y_position": y
            })
        return result

    def is_valid_heading(self, text: str, font_size: float, avg_font_size: float) -> bool:
        if not text or len(text) < 2 or len(text) > 120:
            return False
        if len(text.split()) > 12:
            return False
        if text.lower() in {"table of contents", "index"}:
            return False
        if text.islower():
            return False
        if re.search(r'[.!?]{2,}', text):
            return False
        if sum(1 for w in text.lower().split() if w in self.stopwords) > 4:
            return False
        if font_size < avg_font_size * 0.8:
            return False
        return True

    def _matches_heading_pattern(self, text: str) -> bool:
        patterns = [
            r'^\d+$',
            r'^\d+\.\s',
            r'^\d+\.\d+\s',
            r'^\d+\.\d+\.\d+\s',
            r'^[IVX]+\.\s',
            r'^[A-Z]\.\s',
            r'^\d+(\.\d+)*[:;\s-]+'
            r'^[A-Z][A-Z\s]{2,}$',  # ALL CAPS headings
            r'^[A-Z][a-z\s]+:$',    # Title case with colon
        ]
        return any(re.match(p, text) for p in patterns)

    def classify_heading_level(self, font_size: float, ranked_sizes: List[float]) -> Optional[str]:
        try:
            index = ranked_sizes.index(font_size)
            if index < 5:  # Only allow H1 to H5
                return f"H{index + 1}"
        except ValueError:
            return None
        return None

    def extract_title(self, blocks: List[Dict]) -> str:
        for block in blocks[:10]:
            text = block.get("text", "")
            font_size = block.get("font_size", 12)
            if self.is_valid_heading(text, font_size, font_size) and len(text.split()) <= 10:
                return text
        return "Untitled Document"

    @property
    def stopwords(self):
        return {
            'the', 'and', 'that', 'this', 'with', 'from', 'for', 'was', 'are',
            'have', 'has', 'but', 'also', 'which', 'their', 'there', 'they',
            'will', 'would', 'could', 'should', 'been', 'being', 'does', 'did',
            'can', 'may', 'might', 'must', 'shall', 'through', 'during', 'before',
            'after', 'above', 'below', 'between', 'among', 'within', 'without'
        }

    def extract_outline(self, pdf_path: str) -> Dict:
        logger.info(f"Processing: {pdf_path}")
        start_time = time.time()

        blocks = self.extract_text_with_style(pdf_path)

        # Compute average font size only from valid headings
        valid_blocks = [b for b in blocks if "font_size" in b and self.is_valid_heading(b["text"], b["font_size"], 12)]
        font_sizes = [b["font_size"] for b in valid_blocks]
        avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 12
        ranked_sizes = sorted(set(font_sizes), reverse=True)

        seen = set()
        outline = []

        for block in blocks:
            text = block.get("text", "").strip()
            font_size = block.get("font_size", 12)

            if text in seen or not self.is_valid_heading(text, font_size, avg_font_size):
                continue

            if not self._matches_heading_pattern(text) and len(text.split()) > 6:
                continue

            level = self.classify_heading_level(font_size, ranked_sizes)
            if level:
                outline.append({
                    "level": level,
                    "text": text,
                    "page": block.get("page", 1)
                })
                seen.add(text)

        title = self.extract_title(outline) if outline else "Untitled Document"
        duration = round(time.time() - start_time, 2)

        return {
            "title": title,
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
                output_file = output_path / f"{pdf.stem}.json"
                with open(output_file, "w", encoding="utf-8") as f:
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
