import os
import json
import asyncio
import httpx
import pdfplumber
import argparse
from tqdm import tqdm
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY is not set in .env")

genai.configure(api_key=api_key)

# We use gemini-3.1-flash-lite as it is fast, cost-effective, supported by the API key and has higher rate limits (30 RPM)
model = genai.GenerativeModel('gemini-3.1-flash-lite', 
    generation_config={
        "response_mime_type": "application/json",
        "temperature": 0.1
    }
)

SYSTEM_PROMPT = """You are an expert agronomist extracting tree characteristics from AgroForestree Database profiles.
Extract the following information from the text into a JSON object:
- "species": The scientific name of the species.
- "common_names": List of strings.
- "soil_ph_min": Minimum soil pH (float), null if not specified.
- "soil_ph_max": Maximum soil pH (float), null if not specified.
- "rainfall_min_mm": Minimum annual rainfall (int), null if not specified.
- "rainfall_max_mm": Maximum annual rainfall (int), null if not specified.
- "drought_tolerance": String (e.g., "high", "medium", "low").
- "nitrogen_fixing": Boolean.
- "growth_rate": String (e.g., "fast", "moderate", "slow").
- "uses": List of strings (e.g., ["food", "timber", "fodder", "medicine", "soil improvement"]).
- "soil_texture_preference": List of strings (e.g., ["sand", "loam", "clay"]).

Only output valid JSON matching this structure.
"""

async def download_pdf(http_client: httpx.AsyncClient, url: str, filepath: str):
    if os.path.exists(filepath):
        return True
    
    try:
        response = await http_client.get(url, timeout=30.0)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}", flush=True)
        return False

def extract_text_from_pdf(filepath: str) -> str:
    try:
        text = ""
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text
    except Exception as e:
        print(f"Failed to extract text from {filepath}: {e}", flush=True)
        return ""

async def process_with_llm(text: str) -> dict:
    retries = 5
    backoff = 2
    for attempt in range(retries):
        try:
            prompt = f"{SYSTEM_PROMPT}\n\nPDF Text:\n{text[:20000]}"
            response = await model.generate_content_async(prompt)
            return json.loads(response.text)
        except Exception as e:
            if "ResourceExhausted" in type(e).__name__ or "429" in str(e) or "quota" in str(e).lower():
                wait_time = (backoff ** attempt) * 5 + 5
                print(f"Rate limit hit. Retrying in {wait_time}s... Error: {e}", flush=True)
                await asyncio.sleep(wait_time)
            else:
                print(f"LLM processing failed: {e}", flush=True)
                return None
    print("Failed to process with LLM after multiple retries", flush=True)
    return None

async def process_species(http_client: httpx.AsyncClient, item: dict, db: list, processed_species: set, semaphore: asyncio.Semaphore, write_lock: asyncio.Lock, pbar, args):
    species_name = item['species']
    if species_name in processed_species and not args.force:
        pbar.update(1)
        return
        
    pdf_url = item['pdf_url']
    filename = pdf_url.split('/')[-1]
    filepath = os.path.join(args.pdf_cache, filename)
    
    async with semaphore:
        # Download
        success = await download_pdf(http_client, pdf_url, filepath)
        if not success:
            pbar.update(1)
            return
            
        # Extract Text (run in thread executor to not block event loop)
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, extract_text_from_pdf, filepath)
        if not text:
            pbar.update(1)
            return
            
        # LLM processing
        profile = await process_with_llm(text)
        if profile:
            profile['species'] = species_name
            
            # Save incrementally
            async with write_lock:
                db.append(profile)
                with open(args.output, 'w', encoding='utf-8') as f:
                    json.dump(db, f, indent=2)
                    
        pbar.update(1)

async def main(args):
    # Load species index
    if not os.path.exists(args.species_index):
        print(f"Species index not found at {args.species_index}", flush=True)
        return

    with open(args.species_index, 'r', encoding='utf-8') as f:
        species_list = json.load(f)

    # Load existing DB
    db = []
    if os.path.exists(args.output):
        with open(args.output, 'r', encoding='utf-8') as f:
            db = json.load(f)
    
    processed_species = {entry.get("species") for entry in db}
    
    os.makedirs(args.pdf_cache, exist_ok=True)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    
    # Process batch
    to_process = species_list[args.start_from:]
    if args.batch_size:
        to_process = to_process[:args.batch_size]

    # Concurrency control: rate limit is 30 RPM, so concurrency of 2-3 is very safe
    semaphore = asyncio.Semaphore(2)
    write_lock = asyncio.Lock()
    
    pbar = tqdm(total=len(to_process), desc="Processing species")
    
    async with httpx.AsyncClient(follow_redirects=True) as http_client:
        tasks = []
        for item in to_process:
            tasks.append(
                process_species(
                    http_client, item, db, processed_species, 
                    semaphore, write_lock, pbar, args
                )
            )
        await asyncio.gather(*tasks)
        
    pbar.close()
    print(f"Finished processing batch. Total species in DB: {len(db)}", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest AgroForestree PDFs")
    parser.add_argument("--species-index", default="agroforestree_data/species_index.json")
    parser.add_argument("--pdf-cache", default="agroforestree_data/pdfs")
    parser.add_argument("--output", default="data/species_db.json")
    parser.add_argument("--start-from", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="Reprocess already processed species")
    
    args = parser.parse_args()
    asyncio.run(main(args))
