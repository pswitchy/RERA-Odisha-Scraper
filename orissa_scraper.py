import time
import json
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup, NavigableString

def find_data_by_exact_label(soup, exact_label_text, search_context=None):
    """
    Find data by exact label text in the HTML soup
    """
    if search_context is None:
        search_context = soup
    if soup is None or search_context is None:
        return "Not Found"
    
    # Find label tag with exact matching text (case-insensitive)
    label_tag = search_context.find('label', class_='label-control', 
                                   string=re.compile(r"^\s*" + re.escape(exact_label_text.strip()) + r"\s*$", re.IGNORECASE))
    
    if label_tag:
        # Try to find parent div with specific classes
        parent_div = label_tag.find_parent('div', class_=re.compile(r'details-project'))
        if not parent_div:
            parent_div = label_tag.find_parent('div', class_=re.compile(r'ms-3'))
        if not parent_div:
            parent_div = label_tag.parent
        
        if parent_div:
            # First try to find value in strong tag
            strong_tag = parent_div.find('strong')
            if strong_tag:
                value = strong_tag.get_text(strip=True)
                if value and value.lower() not in ['n/a', '--', 'na', 'not applicable', '']:
                    return value
                elif value == '--':
                    return "Not Found (Placeholder '--' present)"
            
            # Fallback: extract text content from parent div
            value_parts = []
            for content in parent_div.children:
                if content == label_tag:
                    continue
                
                current_text = ""
                if isinstance(content, NavigableString):
                    current_text = content.strip()
                elif content.name == 'br':
                    if value_parts and value_parts[-1] != '\n':
                        value_parts.append('\n')
                    continue
                elif content.name in ['span'] and not content.find(['label', 'span', 'div', 'table', 'strong']):
                    current_text = content.get_text(strip=True)
                
                if current_text:
                    value_parts.append(current_text)
            
            value_candidate = " ".join(value_parts).replace(" \n ", "\n").strip()
            if (value_candidate and 
                value_candidate.lower() not in ['n/a', '--', 'na', 'not applicable', ''] and 
                len(value_candidate) > 0 and len(value_candidate) < 500):
                return value_candidate
    
    return "Not Found"

def extract_project_details_from_soups(overview_soup, promoter_tab_soup):
    """
    Extract project details from HTML soups
    """
    if not overview_soup:
        return None
    
    details = {
        "Rera Regd. No": "Not Found",
        "Project Name": "Not Found", 
        "Promoter Name (Company Name)": "Not Found",
        "Address of the Promoter (Registered Office Address)": "Not Found",
        "GST No.": "Not Found"
    }
    
    print("  DEBUG EXTRACT: Starting extraction...")
    
    # Extract overview details
    overview_app_tag = overview_soup.select_one('app-project-overview')
    project_overview_section = overview_app_tag if overview_app_tag else overview_soup
    
    if overview_app_tag:
        card_body = overview_app_tag.select_one('div.card div.card-body div.row')
        if card_body:
            project_overview_section = card_body
        print("  DEBUG EXTRACT: Using <app-project-overview> for overview fields.")
    else:
        print("  DEBUG EXTRACT: <app-project-overview> NOT FOUND. Using full overview_soup.")
    
    details["Project Name"] = find_data_by_exact_label(project_overview_section, "Project Name")
    details["Rera Regd. No"] = find_data_by_exact_label(project_overview_section, "RERA Regd. No.")
    
    print(f"  DEBUG EXTRACT (Overview): Project Name: {details['Project Name']}, RERA No: {details['Rera Regd. No']}")
    
    # Extract promoter details
    search_context_for_promoter = None
    if promoter_tab_soup:
        promoter_app_tag = promoter_tab_soup.select_one('app-promoter-details')
        if promoter_app_tag:
            specific_promoter_content = promoter_app_tag.select_one('div.promoter div.card-body div.row')
            search_context_for_promoter = specific_promoter_content if specific_promoter_content else promoter_app_tag
            print("  DEBUG EXTRACT: Found context within <app-promoter-details>.")
        else:
            search_context_for_promoter = promoter_tab_soup
            print("  DEBUG EXTRACT: <app-promoter-details> not found. Using whole promoter_tab_soup.")
    else:
        print("  DEBUG EXTRACT: promoter_tab_soup is None.")
    
    if search_context_for_promoter:
        details["Promoter Name (Company Name)"] = find_data_by_exact_label(search_context_for_promoter, "Company Name")
        details["Address of the Promoter (Registered Office Address)"] = find_data_by_exact_label(search_context_for_promoter, "Registered Office Address")
        details["GST No."] = find_data_by_exact_label(search_context_for_promoter, "GST No.")
        
        print(f"  DEBUG EXTRACT (Promoter): Name: {details['Promoter Name (Company Name)']}.")
        print(f"  DEBUG EXTRACT (Promoter): Address: {details['Address of the Promoter (Registered Office Address)']}.")
        print(f"  DEBUG EXTRACT (Promoter): GST: {details['GST No.']}")
    
    return details

def wait_for_page_load_and_list_table(driver, wait, list_url):
    """
    Helper to wait for list page elements after navigation or filter change
    """
    print(f"  Ensuring page is {list_url} and content is loaded...")
    if driver.current_url != list_url:
        driver.get(list_url)
        print(f"  Navigated to {list_url}")
    
    list_page_loader_selector = "ngx-ui-loader > div.ngx-overlay.loading-foreground"
    project_table_id = "tblviewmines"
    
    try:
        print(f"  Waiting for LIST PAGE loader to disappear...")
        wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, list_page_loader_selector)))
        print("  LIST PAGE loader disappeared.")
    except TimeoutException:
        print(f"  Timed out waiting for LIST PAGE loader. Proceeding anyway...")
    
    # Wait for the table to have at least one row
    try:
        print(f"  Waiting for project table to have rows...")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, f"table#{project_table_id} tbody tr")))
        print("  Project table has rows.")
        time.sleep(2)  # Small pause for table rendering
    except TimeoutException:
        print(f"  Timed out waiting for project table rows.")
        raise

def scrape_multiple_projects(list_url, num_projects_to_scrape=6):
    """
    Main function to scrape multiple projects from the list
    """
    all_projects_data = []
    chrome_options = Options()
    
    # Chrome options for headless browsing
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1200")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = None
    
    try:
        # Initialize Chrome driver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        wait = WebDriverWait(driver, 40)
        
        print(f"Navigating to project list: {list_url}")
        wait_for_page_load_and_list_table(driver, wait, list_url)
        
        # Set filter to "Projects Registered"
        try:
            print("Setting status filter to 'Projects Registered'...")
            status_filter_select = wait.until(EC.presence_of_element_located((By.ID, "statusFilter")))
            select = Select(status_filter_select)
            current_filter_value = select.first_selected_option.get_attribute("value")
            
            if current_filter_value != "1":
                print(f"Changing filter from '{current_filter_value}' to '1' (Projects Registered)...")
                select.select_by_value("1")
                print("Filter changed. Waiting for table to reload...")
                wait_for_page_load_and_list_table(driver, wait, list_url)
            else:
                print("'Projects Registered' filter is already active.")
        except TimeoutException:
            print("WARNING: Status filter dropdown not found. Proceeding with current list.")
        except Exception as e:
            print(f"WARNING: Error with status filter: {e}")
        
        # Get project information from the list
        project_table_id = "tblviewmines"
        project_click_targets = []
        project_rows = driver.find_elements(By.CSS_SELECTOR, f"table#{project_table_id} tbody tr")
        
        for i in range(min(num_projects_to_scrape, len(project_rows))):
            row = project_rows[i]
            try:
                tds = row.find_elements(By.TAG_NAME, "td")
                if len(tds) > 4:
                    p_name = tds[2].text  # Project Name is 3rd column
                    p_rera = tds[4].text  # Registration Number is 5th column
                    project_click_targets.append({"index": i, "name": p_name, "rera": p_rera})
                else:
                    print(f"  Row {i} doesn't have enough columns. Skipping.")
            except IndexError:
                print(f"  Could not get name/rera for row {i}. Skipping.")
        
        print(f"Identified {len(project_click_targets)} projects to scrape.")
        
        # Process each project
        for target_info in project_click_targets:
            project_index = target_info["index"]
            print(f"\n--- Processing Project {project_index + 1}: {target_info['name']} ---")
            
            # Re-navigate to list page for fresh state
            print(f"  Re-navigating to list page: {list_url}")
            wait_for_page_load_and_list_table(driver, wait, list_url)
            time.sleep(1)
            
            try:
                # Re-fetch rows and click on details
                all_rows = driver.find_elements(By.CSS_SELECTOR, f"table#{project_table_id} tbody tr")
                if project_index >= len(all_rows):
                    print(f"  Project index {project_index} out of bounds. Skipping.")
                    continue
                
                current_row = all_rows[project_index]
                details_button = WebDriverWait(current_row, 10).until(
                    EC.element_to_be_clickable((By.XPATH, ".//button[contains(@class, 'btn-info') and normalize-space(text())='Details']"))
                )
                
                print(f"  Clicking 'Details' for: {target_info['name']}")
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", details_button)
                time.sleep(1)
                details_button.click()
                
                # Wait for project detail page to load
                page_states = {"initial_load": None, "promoter_tab": None}
                print("  Waiting for project detail overview to load...")
                
                try:
                    # Wait for project name to be populated
                    WebDriverWait(driver, 20).until(
                        lambda d: d.find_element(By.XPATH, 
                            "//app-project-overview//label[@class='label-control' and contains(normalize-space(.), 'Project Name')]/following-sibling::strong[normalize-space(text()) != '--' and normalize-space(text()) != '']"
                        ).is_displayed()
                    )
                    print("  Project Name loaded on detail view.")
                except TimeoutException:
                    print("  Timeout waiting for Project Name. Skipping this project.")
                    continue
                
                time.sleep(2)
                overview_source = driver.page_source
                page_states["initial_load"] = BeautifulSoup(overview_source, 'html.parser')
                
                # Click on Promoter Details tab
                try:
                    promoter_tab_link = WebDriverWait(driver, 15).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "a#ngb-nav-1"))
                    )
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", promoter_tab_link)
                    time.sleep(1)
                    promoter_tab_link.click()
                    print("  'Promoter Details' tab clicked.")
                    
                    # Wait for promoter details to load
                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.XPATH, 
                            "//app-promoter-details//label[@class='label-control' and (contains(normalize-space(.), 'Company Name') or contains(normalize-space(.), 'Name of the Promoter'))]/following-sibling::strong[normalize-space(text()) != '--' and normalize-space(text()) != '']"
                        ))
                    )
                    print("  Promoter Details loaded.")
                    time.sleep(2)
                    page_states["promoter_tab"] = BeautifulSoup(driver.page_source, 'html.parser')
                    
                except Exception as e:
                    print(f"  Error loading Promoter tab: {e}")
                    page_states["promoter_tab"] = page_states["initial_load"]
                
                # Extract project data
                project_data = extract_project_details_from_soups(
                    page_states["initial_load"], 
                    page_states["promoter_tab"]
                )
                
                if project_data:
                    project_data["Original List Name"] = target_info['name']
                    project_data["Original List RERA"] = target_info['rera']
                    all_projects_data.append(project_data)
                
            except StaleElementReferenceException:
                print(f"  StaleElementReferenceException for project {target_info['name']}. Retrying...")
            except Exception as e:
                print(f"  Error processing project {target_info['name']}: {e}")
        
        return all_projects_data
    
    except Exception as e:
        print(f"Major error during scraping: {e}")
        import traceback
        traceback.print_exc()
        return all_projects_data
    
    finally:
        if driver:
            driver.quit()
            print("WebDriver closed.")

def main():
    """
    Main execution function
    """
    # The provided URL
    project_list_url = "https://rera.odisha.gov.in/projectOnlineLists/VTJGc2RHVmtYMStyRFptTFFkemNMVFU4c2Q1UlFOTE1QZVFiQkEzQmI0UT0%3D"
    
    print("Starting RERA Odisha Project Scraper...")
    print(f"Target URL: {project_list_url}")
    print("Scraping first 6 projects under 'Projects Registered'...")
    
    scraped_projects = scrape_multiple_projects(project_list_url, num_projects_to_scrape=6)
    
    if scraped_projects:
        print(f"\n--- SUCCESSFULLY SCRAPED {len(scraped_projects)} PROJECTS ---")
        
        # Create results summary
        results = []
        for idx, data in enumerate(scraped_projects):
            project_result = {
                "Serial No.": idx + 1,
                "Rera Regd. No": data.get("Rera Regd. No", "Not Found"),
                "Project Name": data.get("Project Name", "Not Found"),
                "Promoter Name (Company Name)": data.get("Promoter Name (Company Name)", "Not Found"),
                "Address of the Promoter (Registered Office Address)": data.get("Address of the Promoter (Registered Office Address)", "Not Found"),
                "GST No.": data.get("GST No.", "Not Found")
            }
            results.append(project_result)
            
            print(f"\n--- Project {idx + 1} ---")
            for key, value in project_result.items():
                if key != "Serial No.":
                    print(f"{key}: {value}")
        
        # Save results to JSON file
        with open("rera_projects_data.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4, ensure_ascii=False)
        
        print(f"\n--- SCRAPING COMPLETED ---")
        print(f"Results saved to 'rera_projects_data.json'")
        print(f"Total projects scraped: {len(scraped_projects)}")
        
    else:
        print("\nNo projects were successfully scraped.")
        print("Please check your internet connection and the website availability.")

if __name__ == "__main__":
    main()