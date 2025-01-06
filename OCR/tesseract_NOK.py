import cv2
import pytesseract
import re
import json

# This is not working correctly. We might stick with winocr.

# Point this to your Tesseract installation:
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# 1) Regex to fix bracket misreads ('[3,-5' might have '1' instead of ']'):
fix_brackets_pattern = re.compile(r'(\[-?\d{1,2},-?\d{1,2})1')

# 2) Regexes for extracting info
etape_pattern = re.compile(r'^ÉTAPE\s*:\s*(.+)$', re.IGNORECASE)
depart_pattern = re.compile(r'^Q\s+Départ\s+(\[[^\]]+\])', re.IGNORECASE)
tries_pattern = re.compile(r'(\d+)\s+essais?\s+restants?', re.IGNORECASE)

def parse_ocr_output(lines):
    """
    Extracts:
      - etape (e.g., from "ÉTAPE : 1/4")
      - depart (bracketed coords from "Q Départ [3,-5]")
      - zone (line immediately after "Départ")
      - hints (one or more lines, until "X essais restants")
      - remaining_tries (extracted from "4 essais restants")
    """
    data = {
        "etape": None,
        "depart": None,
        "zone": None,
        "hints": [],
        "remaining_tries": None
    }

    expect_zone = False
    in_hints_section = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 1) Étape
        m_etape = etape_pattern.search(line)
        if m_etape:
            data["etape"] = m_etape.group(1)
            continue

        # 2) Départ
        m_depart = depart_pattern.search(line)
        if m_depart:
            data["depart"] = m_depart.group(1)
            expect_zone = True
            in_hints_section = False
            continue

        # 3) Zone: The line right after "Départ"
        if expect_zone:
            data["zone"] = line
            expect_zone = False
            in_hints_section = True
            continue

        # 4) Remaining Tries
        m_tries = tries_pattern.search(line)
        if m_tries:
            data["remaining_tries"] = int(m_tries.group(1))
            in_hints_section = False  # End hint capture
            continue

        # 5) Otherwise, if we're in hint-collection mode, store the line as a hint
        if in_hints_section:
            data["hints"].append(line)

    return data

def clean_hint(hint_text):
    """
    Remove unwanted symbols, the recurring "EN COURS Q", etc.
    Adjust as needed for your exact text patterns.
    """
    # Remove 'EN COURS Q' in any spacing/case variation:
    hint_text = re.sub(r'\s*EN\s+COURS\s+Q\s*', '', hint_text, flags=re.IGNORECASE)

    # Remove leading non-word characters (like m, $, €, ?, etc.)
    hint_text = re.sub(r'^[^\w]+', '', hint_text)

    # Collapse multiple spaces to a single space
    hint_text = re.sub(r'\s+', ' ', hint_text)

    return hint_text.strip()

def perform_ocr(image_path):
    # Read the image
    image = cv2.imread(image_path)

    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Apply thresholding
    thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)[1]

    # OCR using Tesseract (French)
    recognized_text = pytesseract.image_to_string(thresh, lang='fra')

    # Fix misread brackets (']' read as '1')
    corrected_text = fix_brackets_pattern.sub(r'\1]', recognized_text)
    print("Recognized Text (Corrected):")
    print(corrected_text)

    # Split into lines
    lines = corrected_text.split('\n')

    # Parse the lines
    parsed_data = parse_ocr_output(lines)

    # Clean each hint
    parsed_data["hints"] = [clean_hint(hint_line) for hint_line in parsed_data["hints"]]

    # Show final JSON
    print("\nParsed JSON:")
    print(json.dumps(parsed_data, indent=2, ensure_ascii=False))

    # Optional: draw bounding boxes for each recognized word
    boxes = pytesseract.image_to_data(thresh, lang='fra', output_type=pytesseract.Output.DICT)
    for i, word in enumerate(boxes['text']):
        if word.strip():
            x, y, w, h = boxes['left'][i], boxes['top'][i], boxes['width'][i], boxes['height'][i]
            cv2.rectangle(image, (x, y), (x + w, y + h), (0, 255, 0), 2)

    # Display the image with bounding boxes
    cv2.imshow("OCR Result with Boxes", image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

# Example usage
if __name__ == "__main__":
    perform_ocr("../upscaled_screenshot.png")
