import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import urllib3
import concurrent.futures
from openai import OpenAI
import re
import warnings
from fpdf import FPDF
import base64
import streamlit as st
import json  # Import the standard JSON library
from streamlit_lottie import st_lottie
import time

# --- FUNCTION TO LOAD LOCAL FILE ---
def load_lottiefile(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

# --- LOAD YOUR ANIMATION ---
# Make sure the filename matches exactly!
lottie_coding = load_lottiefile("water.json")

# --- LOADING SCREEN FUNCTION ---
def show_loading_screen():
    placeholder = st.empty()
    with placeholder.container():
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            if lottie_coding:
                st_lottie(lottie_coding, height=300, key="loading_anim")
            else:
                # Fallback if file is missing
                st.spinner("Loading...") 
                st.warning("water.json not found")
                
            st.markdown("<h3 style='text-align: center;'>Filling the Bucket...</h3>", unsafe_allow_html=True)
            
    time.sleep(3) 
    placeholder.empty()

# ... REST OF YOUR IMPORTS AND CONFIG ...

# --- 0. CONFIGURATION ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message=r"\[W008\]", category=UserWarning)

# --- 1. SETUP & SECRETS ---
if "OPENAI_API_KEY" in st.secrets:
    api_key = st.secrets["OPENAI_API_KEY"]
else:
    st.error("🚨 API Key missing! Please create .streamlit/secrets.toml")
    st.stop()

client = OpenAI(api_key=api_key)

# --- PAGE CONFIG ---
st.set_page_config(page_title="PIB Smart Scraper", layout="wide")
st.title("📰 PIB Smart Scraper (Parallel AI + PDF)")
st.markdown("Fetch -> Filter (Parallel) -> On-Demand Summarization")

# --- SIDEBAR INPUTS ---
with st.sidebar:
    st.header("⚙️ Search Configuration")
    search_mode = st.radio("Select Search Mode:", ("Specific Date", "Search by Months"))
    
    selected_day = 0
    selected_months = []
    selected_year = 2024

    if search_mode == "Specific Date":
        st.subheader("📅 Date")
        selected_day = st.number_input("Day", 1, 31, 9)
        m_input = st.number_input("Month", 1, 12, 12)
        selected_months = [m_input]
        selected_year = st.number_input("Year", 2000, 2030, 2024)
    else:
        st.subheader("🗓️ Months")
        selected_year = st.number_input("Year", 2000, 2030, 2024)
        month_map = {"January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6, 
                     "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12}
        month_names = st.multiselect("Select Months:", list(month_map.keys()), default=["January"])
        selected_months = [month_map[m] for m in month_names]
        selected_day = 0

    st.divider()
    st.info("Filtering Model: ")
    st.info("Summarization Model: gpt-4o-mini")

# --- MAIN INPUTS ---
col1, col2 = st.columns([3, 1])
with col1:
    # We use Two-Stage logic: Broad topic for Spacy (removed here as per request for pure OpenAI) 
    # but keeping input simple as "Topic" since we are doing Pure OpenAI now.
    keyword = st.text_input("Enter Topic (e.g. 'Digital India'):")
with col2:
    st.write("##")
    run_button = st.button("🚀 Run Pipeline", use_container_width=True)


# --- HELPER 1: SCRAPE TEXT ---
def get_article_text(url):
    try:
        r = requests.get(url, verify=False, timeout=10)
        s = BeautifulSoup(r.content, "html.parser")
        paragraphs = s.find_all('p')
        text = " ".join([p.text.strip() for p in paragraphs if p.text.strip()])
        return text[:15000]
    except:
        return ""

# --- HELPER 2: GENERATE SUMMARY (STRICT FORMAT) ---
def generate_summary(text):
    prompt = f"""
    Summarize this press release.
    
    REQUIRED FORMAT:
    Context- [What is the main event?]
    Data- [Key numbers, amounts, dates]
    Keywords- [3-5 tags]
    
    Do NOT include the URL in the summary.
    Use proper spacing between sections.
    
    Text:
    {text}
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error: {e}"

# --- HELPER 3: CREATE PDF (ROBUST FIX) ---
def create_pdf(title, summary_text):
    # 1. Define a "Cleaner" that fixes fancy characters
    def make_safe(text):
        if not text: return ""
        # Dictionary of common "illegal" characters -> "safe" replacements
        replacements = {
            '\u2013': '-',   # En dash -> hyphen
            '\u2014': '--',  # Em dash -> double hyphen
            '\u2018': "'",   # Left smart quote -> single quote
            '\u2019': "'",   # Right smart quote -> single quote
            '\u201c': '"',   # Left smart double quote -> double quote
            '\u201d': '"',   # Right smart double quote -> double quote
            '\u2022': '*',   # Bullet point -> asterisk
            '\u2026': '...', # Ellipsis -> dots
            '\u20b9': 'Rs ', # Rupee symbol -> Rs
        }
        for char, replacement in replacements.items():
            text = text.replace(char, replacement)
            
        # NUCLEAR OPTION: Forces text into Latin-1, replacing unknown chars with '?'
        return text.encode('latin-1', 'replace').decode('latin-1')

    pdf = FPDF()
    pdf.add_page()
    
    # 2. Clean BOTH the Title and the Body
    clean_title = make_safe(f"Summary: {title}")
    clean_body = make_safe(summary_text)

    # 3. Add to PDF
    pdf.set_font("Arial", 'B', 16)
    pdf.multi_cell(0, 10, clean_title, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 8, clean_body)
    
    # 4. Return binary output
    return pdf.output(dest="S").encode("latin-1")

# --- HELPER 4: BATCH FILTER ---
def filter_batch_openai(titles, user_query):
    if not titles: return []
    list_text = "\n".join([f"{i}. {t}" for i, t in enumerate(titles)])
    
    prompt = f"""
    Which of these titles match the topic: "{user_query}"?
    Return ONLY index numbers (e.g. 0, 5). If none, return "NONE".
    Titles:
    {list_text}
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        content = response.choices[0].message.content.strip()
        if "NONE" in content.upper(): return []
        found_numbers = re.findall(r'\d+', content)
        return list(set([int(n) for n in found_numbers]))
    except:
        return []

# --- HELPER 5: SCRAPE LINKS ---
def fetch_raw_links(d, m, y):
    target_date_str = f"{d}-{m}-{y}" if d != 0 else f"Month-{m}-{y}"
    base_url = "https://www.pib.gov.in/allRel.aspx?reg=3&lang=1"
    headers = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.pib.gov.in", "Referer": base_url}
    session = requests.Session()
    
    try:
        r = session.get(base_url, headers=headers, verify=False)
        s = BeautifulSoup(r.content, "html.parser")
        viewstate = s.find("input", {"id": "__VIEWSTATE"})["value"]
        eventvalidation = s.find("input", {"id": "__EVENTVALIDATION"})["value"]
        viewstategen = s.find("input", {"id": "__VIEWSTATEGENERATOR"})["value"]
        
        payload = {
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlday", "__EVENTARGUMENT": "", "__LASTFOCUS": "", "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategen, "__VIEWSTATEENCRYPTED": "", "__EVENTVALIDATION": eventvalidation, "ctl00$Bar1$ddlregion": "3",
            "ctl00$Bar1$ddlLang": "1", "ctl00$ContentPlaceHolder1$hydregionid": "3", "ctl00$ContentPlaceHolder1$hydLangid": "1", 
            "ctl00$ContentPlaceHolder1$ddlMinistry": "0", "ctl00$ContentPlaceHolder1$ddlday": str(d), 
            "ctl00$ContentPlaceHolder1$ddlMonth": str(m), "ctl00$ContentPlaceHolder1$ddlYear": str(y)      
        }
        r = session.post(base_url, headers=headers, data=payload, verify=False)
        s = BeautifulSoup(r.content, "html.parser")
        results = []
        content_area = s.find("div", {"class": "content-area"})
        if content_area:
            for link in content_area.find_all("a", href=True):
                if "PressReleasePage.aspx" in link['href'] or "relid=" in link['href'].lower():
                    title = link.get('title', '').strip() or link.text.strip()
                    if title:
                        url = "https://www.pib.gov.in" + link['href'] if not link['href'].startswith("http") else link['href']
                        results.append({"Title": title, "URL": url, "Date": target_date_str})
        return results
    except: return []

# --- EXECUTION FLOW ---
# We use Session State to store results so they don't disappear when you click buttons
if "pipeline_results" not in st.session_state:
    st.session_state.pipeline_results = []

if run_button:
    # 1. SHOW ANIMATION FIRST
    show_loading_screen() 
    
    # 2. THEN START THE ACTUAL WORK
    raw_data = []
    status_box = st.status("🚀 Starting Pipeline...", expanded=True)
    
    # 1. SCRAPE
    status_box.write("📡 Scraping PIB website...")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(fetch_raw_links, selected_day, m, selected_year) for m in selected_months]
        for future in concurrent.futures.as_completed(futures):
            raw_data.extend(future.result())
    
    if not raw_data:
        status_box.update(label="❌ No data found.", state="error")
    else:
        status_box.write(f"📦 Scraped {len(raw_data)} raw items.")
        
        # 2. PARALLEL FILTERING
        # We process batches in parallel using ThreadPoolExecutor
        final_results = []
        
        if keyword:
            status_box.write(f"☁️ Parallel Filtering with OpenAI...")
            BATCH_SIZE = 50
            # Split data into chunks
            chunks = [raw_data[i:i + BATCH_SIZE] for i in range(0, len(raw_data), BATCH_SIZE)]
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Map each chunk to the filter function
                future_to_chunk = {executor.submit(filter_batch_openai, [x['Title'] for x in chunk], keyword): chunk for chunk in chunks}
                
                # Progress bar
                completed = 0
                progress_bar = status_box.progress(0)
                
                for future in concurrent.futures.as_completed(future_to_chunk):
                    chunk = future_to_chunk[future]
                    try:
                        valid_indices = future.result()
                        for idx in valid_indices:
                            if idx < len(chunk):
                                final_results.append(chunk[idx])
                    except Exception as e:
                        print(f"Batch failed: {e}")
                    
                    completed += 1
                    progress_bar.progress(completed / len(chunks))
            
            progress_bar.empty()
        else:
            final_results = raw_data

        status_box.update(label="✅ Pipeline Complete!", state="complete", expanded=False)
        st.session_state.pipeline_results = final_results

# --- DISPLAY RESULTS & SUMMARIZATION LOGIC ---
if st.session_state.pipeline_results:
    st.success(f"Found {len(st.session_state.pipeline_results)} relevant articles.")
    
    results = st.session_state.pipeline_results
    
    # Create a nice layout for each result
    for i, item in enumerate(results):
        with st.container(border=True):
            c1, c2, c3 = st.columns([6, 2, 2])
            
            with c1:
                st.subheader(item['Title'])
                st.caption(f"Date: {item['Date']}")
                st.markdown(f"[Read Full Article]({item['URL']})")
                
            with c2:
                # Unique key for each button is critical
                summ_btn = st.button("📝 Summarize", key=f"btn_{i}", use_container_width=True)
                
            if summ_btn:
                with st.spinner("Generating PDF Summary..."):
                    # 1. Scrape Text
                    full_text = get_article_text(item['URL'])
                    if full_text:
                        # 2. Summarize
                        summary_content = generate_summary(full_text)
                        
                        # 3. Create PDF
                        pdf_bytes = create_pdf(item['Title'], summary_content)
                        b64_pdf = base64.b64encode(pdf_bytes).decode('latin-1')
                        
                        # 4. Show Download Link (Embedded)
                        href = f'<a href="data:application/pdf;base64,{b64_pdf}" download="Summary_{i}.pdf" style="text-decoration:none; color:white; background-color:#FF4B4B; padding:8px 12px; border-radius:5px;">⬇️ Download PDF</a>'
                        
                        with c3:
                            st.markdown(href, unsafe_allow_html=True)
                        
                        # Also show text preview
                        st.text_area("Preview", value=summary_content, height=200, key=f"txt_{i}")
                    else:
                        st.error("Could not fetch article text.")