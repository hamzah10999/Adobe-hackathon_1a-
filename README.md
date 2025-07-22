# 📄 PDF Outline Extractor

This solution automatically extracts a structured outline from PDF files using font size and formatting cues. It processes all PDFs from `/app/input` and saves the generated outlines as `.json` files in `/app/output`.

---

## 🚀 Approach

The solution processes each PDF and identifies headings based on the following characteristics:
- **Font size ranking** (titles and headings usually have larger font sizes)
- **Bold or uppercase text**
- **Relative position on the page**
- **Filtering rules** for noise (e.g. too long, too short, common non-heading text)

Each heading is classified into levels: `H1`, `H2`, `H3`, etc., based on its font size compared to others in the document.

The solution also:
- Calculates the **average font size** across the document.
- Merges fragmented lines from PDFs to ensure coherent headings.
- Detects the document **title** from the largest text block on the first page.

### ⛩ Multilingual Support
- Detects text written in languages like **Japanese**, **Hindi**, **English**, etc.
- Uses `langdetect` for language identification.
- (You can enhance this further with multilingual NLP or OCR if PDFs are image-based.)

---

## 📦 Models & Libraries Used

| Library         | Purpose                                        |
|----------------|------------------------------------------------|
| `pdfplumber`    | PDF text and layout extraction                 |
| `langdetect`    | Language detection for multilingual support    |
| `logging`       | Logging progress and errors                    |
| `json`          | Writing structured output files                |
| `time`          | Measuring performance (time taken per file)    |

---

## 🛠 How to Build & Run the Solution (Documentation Only)

### 🧱 Step 1: Build Docker Image

```bash
 docker build --platform linux/amd64 -t outlineextractor:hamzahv1.

  Step 2: Run the Container
  docker run --rm \
  -v $(pwd)/sample_dataset/input:/app/input \
  -v $(pwd)/sample_dataset/output:/app/output \
  --network none \
  outlineextractor:hamzahv1

Expected Execution Behavior

Your container should:
Read all PDFs from /app/input
Automatically generate one filename.json for each filename.pdf in /app/output
Each .json contains:
title: Document title
time_taken_seconds: Time taken to process that PDF
outline: A list of detected headings with level, text, and page number

Example Output:

{
  "title": "Sample Report",
  "time_taken_seconds": 4.37,
  "outline": [
    { "level": "H1", "text": "Introduction", "page": 0 },
    { "level": "H2", "text": "Background", "page": 1 },
    ...
  ]
}

Directory Structure
pdf-outline-extractor/
sample_dataset/
├── input/     # Place your PDFs here
│   └── *.pdf
└── output/     # JSON results will be saved here
├── Dockerfile
├── requirements.txt
└── main.py              # Main extraction script