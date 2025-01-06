import asyncio
import re
import json
import winocr
from PIL import Image

# Regex to fix bracket misreads:
#   \[          literal '['
#   -?\d{1,2}   optional minus sign, then 1–2 digits
#   ,           comma
#   -?\d{1,2}   optional minus sign, then 1–2 digits
#   )           end capturing group
#   1           literal '1' that we'll replace with ']'
fix_brackets_pattern = re.compile(r'(\[-?\d{1,2},-?\d{1,2})1')

# Regex patterns for parsing data
etape_pattern = re.compile(r'^ÉTAPE\s*:\s*(.+)$', re.IGNORECASE)
depart_pattern = re.compile(r'^Q\s+Départ\s+(\[[^\]]+\])', re.IGNORECASE)
tries_pattern = re.compile(r'(\d+)\s+essais?\s+restants?', re.IGNORECASE)

def parse_ocr_output(lines):
    """Extract Étape, Départ, Zone (the next line after Départ), Hints, and Remaining Tries."""
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

        # 3) Zone (the line right after Départ)
        if expect_zone:
            data["zone"] = line
            expect_zone = False
            in_hints_section = True
            continue

        # 4) Remaining Tries
        m_tries = tries_pattern.search(line)
        if m_tries:
            data["remaining_tries"] = int(m_tries.group(1))
            in_hints_section = False
            continue

        # 5) Hints
        if in_hints_section:
            data["hints"].append(line)

    return data

async def main():
    with Image.open("../upscaled_screenshot.png") as img:
        result = await winocr.recognize_pil(img, "fr")

    # Fix misread brackets in the entire recognized text
    corrected_full_text = fix_brackets_pattern.sub(r'\1]', result.text)
    print("Full text (corrected):")
    print(corrected_full_text)

    print("\nLines (corrected):")
    corrected_lines = []
    for line_obj in result.lines:
        # Fix brackets per line
        line_corrected = fix_brackets_pattern.sub(r'\1]', line_obj.text)
        line_corrected = line_corrected.strip()
        if line_corrected:
            corrected_lines.append(line_corrected)
            print(line_corrected)

    # Parse the corrected lines into structured data
    parsed_data = parse_ocr_output(corrected_lines)

    # Output as JSON
    print("\nParsed JSON:")
    print(json.dumps(parsed_data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
