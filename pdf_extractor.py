#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import logging
import unicodedata
from pathlib import Path
from typing import List, Dict, Optional

try:
    import pdfplumber
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 42
except ImportError:
    print("Missing required module: pdfplumber or langdetect")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PDFOutlineExtractor:
    def normalize_text(self, text: str) -> str:
        return unicodedata.normalize("NFKC", text).strip()

    def detect_language(self, text: str) -> str:
        try:
            return detect(text)
        except Exception:
            return "unknown"

    def extract_text_blocks(self, pdf_path: str) -> List[Dict]:
        blocks = []
        with pdfplumber.open(pdf_path) as pdf:
            default_lang = "unknown"
            for page_num, page in enumerate(pdf.pages):
                if not page.chars:
                    continue
                lines = self._group_and_merge_lines(page.chars)
                for idx, line in enumerate(lines):
                    text = self.normalize_text(line["text"])
                    if page_num == 0 and idx < 3:
                        lang = self.detect_language(text)
                        default_lang = lang
                    else:
                        lang = default_lang
                    blocks.append({
                        "text": text,
                        "font_size": line["font_size"],
                        "font_name": line["font_name"],
                        "lang": lang,
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
                "font_name": data["fonts"][0]
            })

        merged = []
        i = 0
        while i < len(lines):
            current = lines[i]
            while (i + 1 < len(lines) and
                   abs(lines[i + 1]['font_size'] - current['font_size']) < 0.5):
                current['text'] += ' ' + lines[i + 1]['text']
                i += 1
            merged.append(current)
            i += 1
        return merged

    def is_valid_heading(self, text: str, font_size: float, avg_font_size: float, font_name: str, lang: str) -> bool:
        if not text or len(text) < 2 or len(text) > 120:
            return False
        if font_size < avg_font_size * 0.85:
            return False
        if re.search(r'[.!?]{2,}', text):
            return False

        # Match common heading numbering patterns like "1.", "1.1", "2.3.4"
        if re.match(r'^(\d+\.)+\s*\S+', text.strip()):
            return True

        # For Japanese, Chinese, Korean
        if lang in {"ja", "zh", "ko"}:
            return len(text) < 40

        # For Latin-based languages
        if text.lower() in {"table of contents", "index"}:
            return False
        if text.islower():
            return False
        if len(text.split()) > 15:
            return False

        if "bold" in font_name.lower():
            return True
        if text.isupper():
            return True

        return True

    def classify_heading_level(self, font_size: float, ranked_sizes: List[float]) -> Optional[str]:
        try:
            index = ranked_sizes.index(font_size)
            if index < 4:
                return f"H{index + 1}"
        except ValueError:
            return None
        return None

    def extract_title(self, blocks: List[Dict]) -> str:
        if not blocks:
            return "Untitled Document"
        first_page_blocks = [b for b in blocks if b["page"] == 0]
        if not first_page_blocks:
            return "Untitled Document"
        sorted_blocks = sorted(first_page_blocks, key=lambda b: b["font_size"], reverse=True)
        return sorted_blocks[0]["text"].strip()

    def extract_outline(self, pdf_path: str) -> Dict:
        logger.info(f"Processing: {pdf_path}")
        start_time = time.perf_counter()
        blocks = self.extract_text_blocks(pdf_path)

        font_sizes = [b["font_size"] for b in blocks]
        avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 12
        ranked_sizes = sorted(set(font_sizes), reverse=True)

        seen = set()
        outline = []

        for block in blocks:
            text = block["text"]
            size = block["font_size"]
            font = block["font_name"]
            lang = block["lang"]
            if text in seen:
                continue
            if not self.is_valid_heading(text, size, avg_font_size, font, lang):
                continue
            level = self.classify_heading_level(size, ranked_sizes)
            if level:
                outline.append({
                    "level": level,
                    "text": text,
                    "page": block["page"]
                })
                seen.add(text)

        duration = round(time.perf_counter() - start_time, 2)
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
            logger.warning("No PDF files found.")
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
                with open(output_path / f"{pdf.stem}.json", "w", encoding="utf-8") as f:
                    json.dump({
                        "title": f"Error processing {pdf.name}",
                        "time_taken_seconds": 0,
                        "outline": []
                    }, f, ensure_ascii=False, indent=2)


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
