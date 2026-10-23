import pdfplumber
import pandas as pd
import re
from pathlib import Path
import hashlib
from datetime import datetime

# SUPERSEDED (step 15): use backend/scripts/extract_ncrb_table.py, which extracts all 79 table pages
# from the full volume and is validated by backend/scripts/validate_ncrb_table.py. This script's output
# mislabelled crime heads; see docs/analytics/NCRB_CORRECTION.md. Kept for the record.
#
# Configuration
PDF_PATH = Path(r'data/raw/ncrb/vol1-crimeinindia2024.pdf')
OUTPUT_DIR = Path('data/processed/ncrb')
# Table pages 48-79 are PDF pages 95-126 in the Volume I file recorded in data/raw/ncrb/SOURCES.md
# (sha256 5c119c90...); this script originally assumed 93-124.
START_PDF_PAGE = 95
END_PDF_PAGE = 126
START_TABLE_PAGE = 48

# Existing files to verify (must remain unchanged)
EXISTING_RAW_FILE = OUTPUT_DIR / 'ncrb_2024_table_1A4_raw.csv'
EXISTING_STATS_FILE = OUTPUT_DIR / 'ncrb_stats_2024.csv'

# Expected entities (verified from PDF)
EXPECTED_STATES = [
    'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh',
    'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand',
    'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur',
    'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Punjab',
    'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura',
    'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
    'D&N Haveli and Daman & Diu'  # Additional state/UT entity found on page 124
]

EXPECTED_UTS = [
    'A&N Islands', 'Chandigarh', 'Delhi', 'Jammu & Kashmir', 'Ladakh',
    'Lakshadweep', 'Puducherry'
]

EXPECTED_AGGREGATES = ['TOTAL STATE(S)', 'TOTAL UT(S)', 'TOTAL ALL INDIA']

# Crime head mapping (63 blocks)
CRIME_HEAD_MAPPING = [
    ("Rioting - n) Electricity/Power Supply Disputes", "470", "474", "147-151", "190, 189(6), 189(5), 191(2), 191(3)"),
    ("Rioting - o) Sudden Quarrel/Provocation", "475", "479", "147-151", "190, 189(6), 189(5), 191(2), 191(3)"),
    ("Rioting - p) Others", "480", "484", "147-151", "190, 189(6), 189(5), 191(2), 191(3)"),
    ("Unlawful Assembly", "485", "489", "143-145, 149, 150", "188, 189, 191(1)"),
    ("Affray", "490", "494", "160", "192"),
    ("Total Offences against Public Tranquillity", "495", "499", "", ""),
    ("Offences by or Relating to Public Servants - Bribery", "500", "504", "161-165, 165A r/w 511", "..."),
    ("Offences by or Relating to Public Servants - Forgery by Public Servant", "505", "509", "167, 168, 171, 217, 218", "..."),
    ("Offences by or Relating to Public Servants - False Evidence, Fabrication of False Evidence by Public Servant", "510", "514", "191, 192, 193", "..."),
    ("Offences by or Relating to Public Servants - Others", "515", "519", "166, 166A, 166B, 167, 169, 170, 219", "..."),
    ("Total Offences by or Relating to Public Servants", "520", "524", "", ""),
    ("Offences Relating to Elections - Bribery (Elected Representatives)", "525", "529", "171B, 171E, 171F", "..."),
    ("Offences Relating to Elections - Forgery (Elected Representatives)", "530", "534", "171C, 171D", "..."),
    ("Offences Relating to Elections - Others", "535", "539", "171G, 171H, 172 to 186, 188, 189", "..."),
    ("Total Offences Relating to Elections", "540", "544", "", ""),
    ("Counterfeit Currency/Stamp Note", "545", "549", "230 to 254, 257 to 263, 489A-489E", "..."),
    ("Human Trafficking", "550", "554", "366A, 366B, 367, 370, 370A, 371", "..."),
    ("Offences Relating to Marriage", "555", "559", "493 to 498", "..."),
    ("Endangering Life or Personal Safety of Others", "560", "564", "278, 279, 281, 283, 285, 287, 288, 304A", "..."),
    ("Criminal Trespass/Burglary", "565", "569", "442, 443, 447 to 449, 452, 453, 455, 456, 458, 459, 460", "..."),
    ("Mischief", "570", "574", "425, 426, 428 to 440, 462 to 464", "..."),
    ("Intimidation", "575", "579", "503 to 506", "..."),
    ("Insult", "580", "584", "509", "..."),
    ("Offences Relating to Fraud", "585", "589", "415 to 420, 424, 464, 467, 468, 471, 473, 475 r/w 511", "..."),
    ("Prohibition Act", "590", "594", "", ""),
    ("Copyright Act", "595", "599", "", ""),
    ("Railway Property (Unlawful Possession) Act", "600", "604", "", ""),
    ("Excise Act", "605", "609", "", ""),
    ("Essential Commodities Act", "610", "614", "", ""),
    ("Explosive Substance Act", "615", "619", "", ""),
    ("Prevention of Corruption Act", "620", "624", "", ""),
    ("Dowry Prohibition Act", "625", "629", "", ""),
    ("Immoral Traffic (Prevention) Act", "630", "634", "", ""),
    ("Protection of Civil Rights Act", "635", "639", "", ""),
    ("Indian Passport Act", "640", "644", "", ""),
    ("Foreigners Act", "645", "649", "", ""),
    ("Indecent Representation of Women (Prohibition) Act", "650", "654", "", ""),
    ("Information Technology Act", "655", "659", "", ""),
    ("Pre-Conception & Pre-Natal Diagnostic Techniques Act", "660", "664", "", ""),
    ("Scheduled Castes and Scheduled Tribes (Prevention of Atrocities) Act", "665", "669", "", ""),
    ("Protection of Women from Domestic Violence Act", "670", "674", "", ""),
    ("Right to Information Act", "675", "679", "", ""),
    ("Cigarettes and Other Tobacco Products Act", "680", "684", "", ""),
    ("Food Safety and Standards Act", "685", "689", "", ""),
    ("Protection of Children from Sexual Offences Act", "690", "694", "", ""),
    ("Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act", "695", "699", "", ""),
    ("Forest Act", "700", "704", "", ""),
    ("Other SLL Crimes", "705", "709", "", ""),
    ("Total Special & Local Laws (SLL)", "710", "714", "", ""),
    ("Other IPC/BNS Crimes - Adulteration of Food and Drugs", "715", "719", "272 to 276", "..."),
    ("Other IPC/BNS Crimes - Gambling", "720", "724", "294A", "..."),
    ("Other IPC/BNS Crimes - Obscene Acts/Literature", "725", "729", "292, 293", "..."),
    ("Other IPC/BNS Crimes - Offences Relating to Weights and Measures", "730", "734", "264 to 267", "..."),
    ("Other IPC/BNS Crimes - Criminal Negligence", "735", "739", "304A, 336, 337, 338", "..."),
    ("Other IPC/BNS Crimes - Offences Relating to Public Nuisance", "740", "744", "268 to 271, 290, 294", "..."),
    ("Other IPC/BNS Crimes - False Trade Mark", "745", "749", "482 to 489", "..."),
    ("Other IPC/BNS Crimes - Offences Relating to Documents and Property Marks", "750", "754", "463 to 477A", "..."),
    ("Other IPC/BNS Crimes - Offences Relating to Religion", "755", "759", "295 to 298", "..."),
    ("Other IPC/BNS Crimes - Others", "760", "764", "177 to 188, 190, 194 to 216, 219 to 229, 255, 256, 268 to 271", "..."),
    ("Total Other IPC/BNS Crimes", "765", "769", "", ""),
    ("Other Offences", "770", "774", "", ""),
    ("Total IPC/BNS Crimes", "775", "779", "", ""),
    ("Total Cognizable IPC/BNS crimes", "780", "784", "", ""),
]

def calculate_file_hash(filepath):
    """Calculate SHA-256 hash of a file."""
    if not filepath.exists():
        return None
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def verify_existing_files():
    """Verify existing files and record their state."""
    print("=" * 100)
    print("VERIFYING EXISTING FILES (MUST REMAIN UNCHANGED)")
    print("=" * 100)
    
    results = {}
    
    for filepath in [EXISTING_RAW_FILE, EXISTING_STATS_FILE]:
        if filepath.exists():
            df = pd.read_csv(filepath)
            file_hash = calculate_file_hash(filepath)
            file_size = filepath.stat().st_size
            mod_time = datetime.fromtimestamp(filepath.stat().st_mtime)
            
            results[filepath.name] = {
                'rows': len(df),
                'hash': file_hash[:16] + '...',
                'full_hash': file_hash,
                'size': file_size,
                'modified': mod_time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            print(f"\n{filepath.name}:")
            print(f"  Rows: {len(df)}")
            print(f"  SHA-256: {file_hash}")
            print(f"  Size: {file_size} bytes")
            print(f"  Modified: {mod_time}")
        else:
            print(f"\n{filepath.name}: NOT FOUND")
            results[filepath.name] = None
    
    return results

def extract_entity_from_row(row_text):
    """
    Extract entity name from a row, handling all cases including aggregates.
    Returns list of (entity_name, remaining_text) tuples for rows with multiple entities.
    """
    entities = []
    
    # Check if row contains multiple aggregate rows (merged by pdfplumber)
    if '\n' in row_text:
        # Split by newline and process each part
        parts = row_text.split('\n')
        for part in parts:
            part = part.strip()
            if part:
                entity_results = extract_entity_from_row(part)
                entities.extend(entity_results)
        return entities
    
    # Single row processing
    # Check for aggregates first (they don't have serial numbers)
    if 'TOTAL STATE(S)' in row_text:
        # Extract the part after TOTAL STATE(S)
        remaining = row_text.split('TOTAL STATE(S)', 1)[1].strip()
        return [('TOTAL STATE(S)', remaining)]
    elif 'TOTAL UT(S)' in row_text:
        remaining = row_text.split('TOTAL UT(S)', 1)[1].strip()
        return [('TOTAL UT(S)', remaining)]
    elif 'TOTAL ALL INDIA' in row_text:
        remaining = row_text.split('TOTAL ALL INDIA', 1)[1].strip()
        return [('TOTAL ALL INDIA', remaining)]
    else:
        # Try to extract state/UT name with serial number
        match = re.match(r'^\d+\s+([A-Za-z\s&]+?)(?=\s+\d)', row_text)
        if match:
            entity_name = match.group(1).strip()
            remaining = row_text[match.end():].strip()
            return [(entity_name, remaining)]
    
    return []

def extract_numbers_from_text(text):
    """Extract numerical blocks (5 numbers) from text."""
    numbers = re.findall(r'\d+', text)
    
    # Group into 5-number blocks: [IPC] [BNS] [Total] [V] [R]
    blocks = []
    i = 0
    while i + 4 < len(numbers):
        block = {
            'ipc': int(numbers[i]),
            'bns': int(numbers[i+1]),
            'total': int(numbers[i+2]),
            'v': int(numbers[i+3]),
            'r': numbers[i+4]  # Could be decimal
        }
        blocks.append(block)
        i += 5
    
    return blocks

def extract_with_aggregate_fix(pdf_path, start_page, end_page):
    """
    Extract data with proper aggregate row handling.
    Splits merged rows and extracts each entity separately.
    """
    print("\n" + "=" * 100)
    print(f"FIXED COORDINATE-AWARE EXTRACTION WITH AGGREGATE ROW SPLITTING")
    print("=" * 100)
    
    all_records = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for pdf_page_num in range(start_page, end_page + 1):
            page_idx = pdf_page_num - 1
            table_page = START_TABLE_PAGE + (pdf_page_num - START_PDF_PAGE)
            
            print(f"\nProcessing PDF page {pdf_page_num} (Table page {table_page})...")
            
            page = pdf.pages[page_idx]
            table = page.extract_table({
                'vertical_strategy': 'lines',
                'horizontal_strategy': 'lines',
                'snap_tolerance': 3,
                'join_tolerance': 3,
                'edge_min_length': 3,
            })
            
            if not table:
                print(f"  WARNING: No table extracted from page {pdf_page_num}")
                continue
            
            # Process each row
            row_count = 0
            for row in table:
                if not row or not any(row):
                    continue
                
                # Combine cells
                row_text = ' '.join([str(cell) if cell else '' for cell in row])
                
                # Skip headers and section markers
                if any(x in row_text for x in ['State/UT', 'IPC', 'BNS', '[', 'STATES:', 'UTs:']):
                    continue
                
                # Extract entities (handles merged rows)
                entity_results = extract_entity_from_row(row_text)
                
                if not entity_results:
                    continue
                
                # Process each entity found in this row
                for entity_name, remaining_text in entity_results:
                    # Extract numerical blocks
                    blocks = extract_numbers_from_text(remaining_text)
                    
                    # Determine which crime heads are on this page
                    crime_heads_on_page = CRIME_HEAD_MAPPING[(table_page - START_TABLE_PAGE) * 2: (table_page - START_TABLE_PAGE + 1) * 2]
                    
                    # Match blocks to crime heads
                    for block_idx, (crime_head_name, col_start, col_end, ipc_sec, bns_sec) in enumerate(crime_heads_on_page):
                        if block_idx < len(blocks):
                            block = blocks[block_idx]
                            case_count = block['total']
                            
                            record = {
                                'year': 2024,
                                'table_page': table_page,
                                'pdf_page': pdf_page_num,
                                'state': entity_name,
                                'offense_category': crime_head_name,
                                'column_start': col_start,
                                'column_end': col_end,
                                'ipc_section': ipc_sec,
                                'bns_section': bns_sec,
                                'case_count_raw': str(case_count),
                                'case_count': case_count,
                                'extraction_method': 'pdfplumber_aggregate_fixed',
                                'confidence': 'HIGH',
                                'verification_status': 'AUTO_EXTRACTED'
                            }
                            
                            all_records.append(record)
                            row_count += 1
            
            print(f"  Extracted {row_count} records from page {pdf_page_num}")
    
    return pd.DataFrame(all_records)

def main():
    print("NCRB Table 1A.4 Extraction - Pages 48-79 (PDF 93-124)")
    print("=" * 100)
    print(f"Start time: {datetime.now()}")
    print(f"\nExpected structure: 29 states + 7 UTs + 3 aggregates = 39 entities per crime head")
    print(f"Expected rows: 39 × 63 crime heads = 2,457")
    
    # Step 1: Verify existing files
    existing_state = verify_existing_files()
    
    # Step 2: Extract data with aggregate fix
    df_raw = extract_with_aggregate_fix(PDF_PATH, START_PDF_PAGE, END_PDF_PAGE)
    
    print(f"\n{'=' * 100}")
    print(f"EXTRACTION COMPLETE")
    print(f"{'=' * 100}")
    print(f"Total records extracted: {len(df_raw)}")
    print(f"NULL case counts: {df_raw['case_count'].isna().sum()}")
    print(f"Explicit zeros: {(df_raw['case_count'] == 0).sum()}")
    print(f"HIGH confidence: {(df_raw['confidence'] == 'HIGH').sum()}")
    
    # Entity counts
    unique_states = df_raw['state'].unique()
    print(f"\nUnique entities: {len(unique_states)}")
    print(f"  States: {len([s for s in unique_states if s in EXPECTED_STATES])}")
    print(f"  UTs: {len([s for s in unique_states if s in EXPECTED_UTS])}")
    print(f"  Aggregates: {len([s for s in unique_states if s in EXPECTED_AGGREGATES])}")
    
    # Step 3: Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    raw_output = OUTPUT_DIR / 'ncrb_2024_table_1A4_pages_48_79_raw.csv'
    df_raw.to_csv(raw_output, index=False)
    print(f"\nSaved: {raw_output}")
    
    # Step 4: Create standardized format
    df_std = df_raw[['year', 'state', 'offense_category', 'ipc_section', 'bns_section', 'case_count']].copy()
    df_std['conviction_count'] = None
    df_std['acquittal_count'] = None
    
    std_output = OUTPUT_DIR / 'ncrb_stats_2024_pages_48_79.csv'
    df_std.to_csv(std_output, index=False)
    print(f"Saved: {std_output}")
    
    # Step 5: Verify existing files unchanged
    print(f"\n{'=' * 100}")
    print("VERIFYING EXISTING FILES REMAIN UNCHANGED")
    print(f"{'=' * 100}")
    
    for filepath in [EXISTING_RAW_FILE, EXISTING_STATS_FILE]:
        if filepath.exists():
            current_hash = calculate_file_hash(filepath)
            original_hash = existing_state[filepath.name]['full_hash'] if existing_state.get(filepath.name) else None
            
            if current_hash == original_hash:
                print(f"{filepath.name}: ✓ UNCHANGED")
            else:
                print(f"{filepath.name}: ✗ MODIFIED (ERROR!)")
    
    print(f"\nEnd time: {datetime.now()}")

if __name__ == '__main__':
    main()
