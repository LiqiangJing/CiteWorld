import folium
import itertools
import pandas as pd
import os
import pickle
import pycountry
import re
import random
import time

from geopy.geocoders import Nominatim
from multiprocessing import Pool
# from scholarly import scholarly, ProxyGenerator
from tqdm import tqdm
from typing import Any, List, Tuple, Optional

from schoarly_support_new import get_citing_author_ids_and_citing_papers, get_organization_name, NO_AUTHOR_FOUND_STR, KNOWN_AFFILIATION_DICT
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = None


def create_driver(chromedriver):
    global driver
    if driver is None:
        service = Service(chromedriver)
        driver = webdriver.Chrome(service=service)
        print("[INFO] Browser opened. You can solve CAPTCHAs (if prompted) in the browser window.")
        print("[INFO] KEEP THE POP-UP BROWSER OPEN until the CitationMap program is complete.")
    return driver

def affiliations_from_authors_conservative_selenium(citing_author_paper_info, driver):
    """
    简化版 conservative：直接拿 profile 上的第一行 affiliation，
    然后再用你原来的 clean_affiliation_names 去做更严格清洗。
    """
    citing_author_id, citing_paper_title, cited_paper_title = citing_author_paper_info
    if citing_author_id == NO_AUTHOR_FOUND_STR:
        return (NO_AUTHOR_FOUND_STR, citing_paper_title, cited_paper_title, NO_AUTHOR_FOUND_STR)

    time.sleep(random.uniform(1, 5))
    name, affiliation = get_author_name_and_affiliation_selenium(citing_author_id, driver)

    if not affiliation:
        return None
    return (name, citing_paper_title, cited_paper_title, affiliation)


def affiliations_from_authors_aggressive_selenium(citing_author_paper_info, driver):
    """
    aggressive 其实也一样，从 profile 把整段 affiliation 字符串拿回来即可，
    后面你的 clean_affiliation_names 会做拆分 + 清洗。
    """
    citing_author_id, citing_paper_title, cited_paper_title = citing_author_paper_info
    if citing_author_id == NO_AUTHOR_FOUND_STR:
        return (NO_AUTHOR_FOUND_STR, citing_paper_title, cited_paper_title, NO_AUTHOR_FOUND_STR)

    time.sleep(random.uniform(1, 5))
    name, affiliation = get_author_name_and_affiliation_selenium(citing_author_id, driver)
    if not affiliation:
        return None
    return (name, citing_paper_title, cited_paper_title, affiliation)



def _expand_all_publications(driver, max_clicks: int = 50, wait_seconds: int = 5):
    """
    不停点击作者页面底部的 "Show more"，直到没有更多论文可展开。
    """
    clicks = 0
    while clicks < max_clicks:
        try:
            # 等待按钮出现并可点击
            more_btn = WebDriverWait(driver, wait_seconds).until(
                EC.element_to_be_clickable((By.ID, "gsc_bpf_more"))
            )
        except Exception:
            # 找不到按钮，直接退出
            break

        # 检查是否已经 disabled
        btn_class = more_btn.get_attribute("class") or ""
        if "disabled" in btn_class:
            break

        try:
            more_btn.click()
            clicks += 1
            time.sleep(2)  # 给页面一点加载时间
        except Exception:
            # 点击失败就退出，避免死循环
            break

    print(f"[INFO] Finished clicking 'Show more'. Total clicks: {clicks}")

def get_publications_with_cites_ids_selenium(scholar_id: str,
                                             driver,
                                             max_clicks: int = 50):
    """
    用 Selenium 从作者主页抓取 (cites_id, paper_title) 列表：
    1）先点击所有 'Show more' 展开全部论文
    2）再统一解析一次页面，去重
    """
    url = f"https://scholar.google.com/citations?hl=en&user={scholar_id}&view_op=list_works&sortby=pubdate"
    driver.get(url)
    time.sleep(2)

    # 先把所有论文展开
    _expand_all_publications(driver, max_clicks=max_clicks)

    # 一次性解析全部 HTML
    soup = BeautifulSoup(driver.page_source, "html.parser")
    rows = soup.select("tr.gsc_a_tr")

    results = []
    seen_cites_ids = set()
    print(f"Total{len(rows)} publications")
    for row in rows:
        title_el = row.select_one("a.gsc_a_at")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)

        cites_el = row.select_one("a.gsc_a_ac")

        if not cites_el:
            continue

        href = cites_el.get("href", "")
        m = re.search(r"cites=([^&]+)", href)

        if not m:
            # 没有 cites= 的，说明这篇还没被引用（Cited by 0），按你之前逻辑可以直接跳过
            continue

        cites_id = m.group(1)

        # 用 cites_id 去重，保证每篇论文只记录一次
        if cites_id in seen_cites_ids:
            continue
        seen_cites_ids.add(cites_id)

        results.append((cites_id, title))

    print(f"[INFO] Parsed {len(results)} publications with citations.")
    return results


def find_all_citing_authors(scholar_id: str, num_processes: int = 16) -> List[Tuple[str]]:
    '''
    Step 1. Find all publications of the given Google Scholar ID.
    Step 2. Find all citing authors.
    '''
    # Find Google Scholar Profile using Scholar ID.
    # author = scholarly.search_author_id(scholar_id)
    # author = scholarly.fill(author, sections=['publications'])
    all_publication_info = get_publications_with_cites_ids_selenium(scholar_id, driver)
    all_publication_info = list(set(all_publication_info))
    print('Author profile found, with %d publications.\n' % len(all_publication_info))

    print(all_publication_info)

    all_citing_author_paper_tuple_list = []
    for pub in tqdm(all_publication_info,
                    desc='Finding citing authors and papers on your %d publications' % len(all_publication_info),
                    total=len(all_publication_info)):
        all_citing_author_paper_tuple_list.extend(__citing_authors_and_papers_from_publication(pub))

    return all_citing_author_paper_tuple_list


def get_author_name_and_affiliation_selenium(author_id: str, driver):
    """
    访问作者 profile 页，解析名字和 affiliation 文本。
    conservative/aggressive 的差别后面可以靠正则清洗。
    """
    url = f"https://scholar.google.com/citations?hl=en&user={author_id}"
    driver.get(url)
    time.sleep(2)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    # 名字一般在 <div id="gsc_prf_in"> 里
    name_el = soup.select_one("#gsc_prf_in")
    name = name_el.get_text(strip=True) if name_el else NO_AUTHOR_FOUND_STR

    # Affiliation 在第一个 class="gsc_prf_il" 中，后面可能还有 email、interests 等
    aff_el = soup.select_one(".gsc_prf_il")
    affiliation = aff_el.get_text(strip=True) if aff_el else ""

    return name, affiliation

def find_all_citing_affiliations_selenium(all_citing_author_paper_tuple_list,
                                            driver,
                                            affiliation_conservative: bool = False):
    if affiliation_conservative:
        fn = lambda item: affiliations_from_authors_conservative_selenium(item, driver)
    else:
        fn = lambda item: affiliations_from_authors_aggressive_selenium(item, driver)

    author_paper_affiliation_tuple_list = []
    for author_and_paper in tqdm(all_citing_author_paper_tuple_list,
                                 desc='Finding citing affiliations from %d citing authors' % len(all_citing_author_paper_tuple_list),
                                 total=len(all_citing_author_paper_tuple_list)):
        res = fn(author_and_paper)
        if res:
            author_paper_affiliation_tuple_list.append(res)

    return author_paper_affiliation_tuple_list


def clean_affiliation_names(author_paper_affiliation_tuple_list: List[Tuple[str]]) -> List[Tuple[str]]:
    '''
    Optional Step. Clean up the names of affiliations from the authors' affiliation tab on their Google Scholar profiles.
    NOTE: This logic is very naive. Please send an issue or pull request if you have any idea how to improve it.
    Currently we will not consider any paid service or tools that pose extra burden on the users, such as GPT API.
    '''
    cleaned_author_paper_affiliation_tuple_list = []
    for author_name, citing_paper_title, cited_paper_title, affiliation_string in author_paper_affiliation_tuple_list:
        if author_name == NO_AUTHOR_FOUND_STR:
            cleaned_author_paper_affiliation_tuple_list.append((NO_AUTHOR_FOUND_STR, citing_paper_title, cited_paper_title, NO_AUTHOR_FOUND_STR))
        else:
            # Use a regular expression to split the string by ';' or 'and'.
            substring_list = [part.strip() for part in re.split(r'[;]|\band\b', affiliation_string)]
            # Further split the substrings by ',' if the latter component is not a country.
            substring_list = __country_aware_comma_split(substring_list)

            for substring in substring_list:
                # Use a regular expression to remove anything before 'at', or '@'.
                cleaned_affiliation = re.sub(r'.*?\bat\b|.*?@', '', substring, flags=re.IGNORECASE).strip()
                # Use a regular expression to filter out strings that represent
                # a person's identity rather than affiliation.
                is_common_identity_string = re.search(
                    re.compile(
                        r'\b(director|manager|chair|engineer|programmer|scientist|professor|lecturer|phd|ph\.d|postdoc|doctor|student|department of)\b',
                        re.IGNORECASE),
                    cleaned_affiliation)
                if not is_common_identity_string:
                    cleaned_author_paper_affiliation_tuple_list.append((author_name, citing_paper_title, cited_paper_title, cleaned_affiliation))
    return cleaned_author_paper_affiliation_tuple_list

def fill_known_affiliations(affiliation_name: str) -> Optional[str]:
    '''
    If the affiliation is known, return its geolocation.
    If not, return None.
    The reason we have this function is taht geolocator may return hilarious results,
    such as putting the company Amazon in Amazon rain forest.
    NOTE: This is a temporal fix. Can be replaced by smarter natural language parsers.
    '''
    for key in KNOWN_AFFILIATION_DICT:
        if key in affiliation_name.lower():
            return KNOWN_AFFILIATION_DICT[key]
    return None

def affiliation_invalid(affiliation_name: str) -> bool:
    '''
    Check if the affiliation is invalid.
    Typical invalid affiliation contains non-affiliation words, such as 'computer science'.
    Invalid affiliations will waste time in geolocator.geocode(affiliation_name).
    NOTE: This is a temporal fix. Can be replaced by smarter natural language parsers.
    '''
    invalid_affiliation_set = {
        NO_AUTHOR_FOUND_STR.lower(),
        'computer', 'computer science', 'electrical', 'engineering', 'researcher',
        'scholar', 'inc.', 'school', 'department', 'student', 'candidate', 'professor', 'faculty', 'associate'
    }
    for key in invalid_affiliation_set:
        if key in affiliation_name.lower():
            return True
    return False

def affiliation_text_to_geocode(author_paper_affiliation_tuple_list: List[Tuple[str]], max_attempts: int = 3) -> List[Tuple[str]]:
    '''
    Step 4: Convert affiliations in plain text to Geocode.
    '''
    coordinates_and_info = []
    # NOTE: According to the Nominatim Usage Policy (https://operations.osmfoundation.org/policies/nominatim/),
    # we are explicitly asked not to submit bulk requests on multiple threads.
    # Therefore, we will keep it to a loop instead of multiprocessing.
    geolocator = Nominatim(user_agent='citation_mapper')

    # Find unique affiliations and record their corresponding entries.
    affiliation_map = {}
    for entry_idx, (_, _, _, affiliation_name) in enumerate(author_paper_affiliation_tuple_list):
        if affiliation_name not in affiliation_map.keys():
            affiliation_map[affiliation_name] = [entry_idx]
        else:
            affiliation_map[affiliation_name].append(entry_idx)

    num_total_affiliations = len(affiliation_map)
    num_located_affiliations = 0
    for affiliation_name in tqdm(affiliation_map,
                                 desc='Finding geographic coordinates from %d unique citing affiliations in %d entries' % (
                                     len(affiliation_map), len(author_paper_affiliation_tuple_list)),
                                 total=len(affiliation_map)):
        if affiliation_invalid(affiliation_name):
            # If an affiliation is invalid, we will not run geolocator on it.
            # However, we still record it in the csv, so that the user can choose to manually correct it.
            corresponding_entries = affiliation_map[affiliation_name]
            for entry_idx in corresponding_entries:
                author_name, citing_paper_title, cited_paper_title, affiliation_name = author_paper_affiliation_tuple_list[entry_idx]
                coordinates_and_info.append((author_name, citing_paper_title, cited_paper_title, affiliation_name,
                                            '', '', '', '', '', ''))
        else:
            # Directly enter information if the affiliation is known.
            geo_location = fill_known_affiliations(affiliation_name)
            if geo_location is not None:
                county, city, state, country, latitude, longitude = geo_location
                corresponding_entries = affiliation_map[affiliation_name]
                for entry_idx in corresponding_entries:
                    author_name, citing_paper_title, cited_paper_title, affiliation_name = author_paper_affiliation_tuple_list[entry_idx]
                    coordinates_and_info.append((author_name, citing_paper_title, cited_paper_title, affiliation_name,
                                                latitude, longitude, county, city, state, country))
                # This location is successfully recorded.
                num_located_affiliations += 1
            else:
                for _ in range(max_attempts):
                    try:
                        geo_location = geolocator.geocode(affiliation_name)
                        if geo_location is not None:
                            # Get the full location metadata that includes county, city, state, country, etc.
                            location_metadata = geolocator.reverse(str(geo_location.latitude) + ',' + str(geo_location.longitude), language='en')
                            address = location_metadata.raw['address']
                            county, city, state, country = None, None, None, None
                            if 'county' in address:
                                county = address['county']
                            if 'city' in address:
                                city = address['city']
                            if 'state' in address:
                                state = address['state']
                            if 'country' in address:
                                country = address['country']

                            corresponding_entries = affiliation_map[affiliation_name]
                            for entry_idx in corresponding_entries:
                                author_name, citing_paper_title, cited_paper_title, affiliation_name = author_paper_affiliation_tuple_list[entry_idx]
                                coordinates_and_info.append((author_name, citing_paper_title, cited_paper_title, affiliation_name,
                                                            geo_location.latitude, geo_location.longitude,
                                                            county, city, state, country))
                            # This location is successfully recorded.
                            num_located_affiliations += 1
                            break
                    except:
                        continue
    print('\nConverted %d/%d affiliations to Geocodes.' % (num_located_affiliations, num_total_affiliations))
    coordinates_and_info = [item for item in coordinates_and_info if item is not None]  # Filter out empty entries.
    return coordinates_and_info

def export_dict_to_csv(coordinates_and_info: List[Tuple[str]], csv_output_path: str) -> None:
    '''
    Step 5.1: Export csv file recording citation information.
    '''

    citation_df = pd.DataFrame(coordinates_and_info,
                               columns=['citing author name', 'citing paper title', 'cited paper title',
                                        'affiliation', 'latitude', 'longitude',
                                        'county', 'city', 'state', 'country'])

    citation_df.to_csv(csv_output_path)
    return

def read_csv_to_dict(csv_path: str) -> None:
    '''
    Step 5.1: Read csv file recording citation information.
    Only relevant if `read_from_csv` is True.
    '''

    citation_df = pd.read_csv(csv_path, index_col=0)
    coordinates_and_info = list(citation_df.itertuples(index=False, name=None))
    return coordinates_and_info

def create_map(coordinates_and_info: List[Tuple[str]], pin_colorful: bool = True):
    '''
    Step 5.2: Create the Citation World Map.

    For authors under the same affiliations, they will be displayed in the same pin.
    '''
    citation_map = folium.Map(location=[20, 0], zoom_start=2)

    # Find unique affiliations and record their corresponding entries.
    affiliation_map = {}
    for entry_idx, (_, _, _, affiliation_name, _, _, _, _, _, _) in enumerate(coordinates_and_info):
        if affiliation_name == NO_AUTHOR_FOUND_STR:
            continue
        elif affiliation_name not in affiliation_map.keys():
            affiliation_map[affiliation_name] = [entry_idx]
        else:
            affiliation_map[affiliation_name].append(entry_idx)

    if pin_colorful:
        colors = ['red', 'blue', 'green', 'purple', 'orange', 'darkred',
                  'lightred', 'beige', 'darkblue', 'darkgreen', 'cadetblue',
                  'darkpurple', 'pink', 'lightblue', 'lightgreen',
                  'gray', 'black', 'lightgray']
        for affiliation_name in affiliation_map:
            color = random.choice(colors)
            corresponding_entries = affiliation_map[affiliation_name]
            author_name_list = []
            location_valid = True
            for entry_idx in corresponding_entries:
                author_name, _, _, _, lat, lon, _, _, _, _  = coordinates_and_info[entry_idx]
                if pd.isna(lat) or pd.isna(lon) or lat == '' or lon == '':
                    location_valid = False
                author_name_list.append(author_name)
            if location_valid:
                folium.Marker([lat, lon], popup='%s (%s)' % (affiliation_name, ' & '.join(author_name_list)),
                            icon=folium.Icon(color=color)).add_to(citation_map)
    else:
        for affiliation_name in affiliation_map:
            corresponding_entries = affiliation_map[affiliation_name]
            author_name_list = []
            location_valid = True
            for entry_idx in corresponding_entries:
                author_name, _, _, _, lat, lon, _, _, _, _  = coordinates_and_info[entry_idx]
                if pd.isna(lat) or pd.isna(lon) or lat == '' or lon == '':
                    location_valid = False
                author_name_list.append(author_name)
            if location_valid:
                folium.Marker([lat, lon], popup='%s (%s)' % (affiliation_name, ' & '.join(author_name_list))).add_to(citation_map)
    return citation_map

def count_citation_stats(coordinates_and_info: List[Tuple[str]]) -> List[int]:
    '''
    Count the number of citing authors, affiliations and countries.
    '''
    unique_author_list, unique_affiliation_list, unique_country_list = set(), set(), set()
    for (author_name, _, _, affiliation_name, _, _, _, _, _, country) in coordinates_and_info:
        if affiliation_name == NO_AUTHOR_FOUND_STR:
            continue
        unique_author_list.add(author_name)
        unique_affiliation_list.add(affiliation_name)
        unique_country_list.add(country)
        num_authors, num_affiliations, num_countries = \
            len(unique_author_list), len(unique_affiliation_list), len(unique_country_list)
    return num_authors, num_affiliations, num_countries


def __citing_authors_and_papers_from_publication(cites_id_and_cited_paper: Tuple[str, str]):
    cites_id, cited_paper_title = cites_id_and_cited_paper
    citing_paper_search_url = 'https://scholar.google.com/scholar?hl=en&cites=' + cites_id
    # print(citing_paper_search_url)
    citing_authors_and_citing_papers = get_citing_author_ids_and_citing_papers(citing_paper_search_url, driver)
    citing_author_paper_info = []
    for citing_author_id, citing_paper_title in citing_authors_and_citing_papers:
        citing_author_paper_info.append((citing_author_id, citing_paper_title, cited_paper_title))
    return citing_author_paper_info

def __country_aware_comma_split(string_list: List[str]) -> List[str]:
    comma_split_list = []

    for part in string_list:
        # Split the strings by comma.
        # NOTE: The non-English comma is entered intentionally.
        sub_parts = [sub_part.strip() for sub_part in re.split(r'[,，]', part)]
        sub_parts_iter = iter(sub_parts)

        # Merge the split strings if the latter component is a country name.
        for sub_part in sub_parts_iter:
            if __iscountry(sub_part):
                continue  # Skip country names if they appear as the first sub_part.
            next_part = next(sub_parts_iter, None)
            if __iscountry(next_part):
                comma_split_list.append(f"{sub_part}, {next_part}")
            else:
                comma_split_list.append(sub_part)
                if next_part:
                    comma_split_list.append(next_part)
    return comma_split_list

def __iscountry(string: str) -> bool:
    try:
        pycountry.countries.lookup(string)
        return True
    except LookupError:
        return False

def __print_author_and_affiliation(author_paper_affiliation_tuple_list: List[Tuple[str]]) -> None:
    __author_affiliation_tuple_list = []
    for author_name, _, _, affiliation_name in sorted(author_paper_affiliation_tuple_list):
        if author_name == NO_AUTHOR_FOUND_STR:
            continue
        __author_affiliation_tuple_list.append((author_name, affiliation_name))

    # Take unique tuples.
    __author_affiliation_tuple_list = list(set(__author_affiliation_tuple_list))
    for author_name, affiliation_name in sorted(__author_affiliation_tuple_list):
        print('Author: %s. Affiliation: %s.' % (author_name, affiliation_name))
    print('')
    return


def save_cache(data: Any, fpath: str) -> None:
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "wb") as fd:
        pickle.dump(data, fd)

def load_cache(fpath: str) -> Any:
    with open(fpath, "rb") as fd:
        return pickle.load(fd)

def generate_citation_map_selenium(scholar_id: str,
                                   output_path: str = 'citation_map.html',
                                   csv_output_path: str = 'citation_info.csv',
                                   parse_csv: bool = False,
                                   cache_folder: str = 'cache',
                                   affiliation_conservative: bool = False,
                                   pin_colorful: bool = True,
                                   print_citing_affiliations: bool = True,
                                   chromedriver: str = "chromedriver-mac-arm64/chromedriver"):
    driver = create_driver(chromedriver)

    if cache_folder is not None:
        cache_path = os.path.join(cache_folder, scholar_id, 'all_citing_author_paper_tuple_list.pkl')
        csv_output_path = os.path.join(cache_folder, scholar_id, csv_output_path)
        output_path = os.path.join(cache_folder, scholar_id, output_path)
    else:
        cache_path = None

    try:
        if not parse_csv:
            # Step 1 & 2: citing authors
            all_citing_author_paper_tuple_list = find_all_citing_authors(scholar_id, driver)
            print('A total of %d citing authors recorded.\n' % len(all_citing_author_paper_tuple_list))

            if cache_path is not None and len(all_citing_author_paper_tuple_list) > 0:
                save_cache(all_citing_author_paper_tuple_list, cache_path)
            print('Saved to cache: %s.\n' % cache_path)

            if cache_folder is not None:
                cache_path = os.path.join(cache_folder, scholar_id, 'author_paper_affiliation_tuple_list.pkl')
            else:
                cache_path = None

            # Step 3: citing affiliations
            author_paper_affiliation_tuple_list = find_all_citing_affiliations_selenium(
                all_citing_author_paper_tuple_list,
                driver,
                affiliation_conservative=affiliation_conservative
            )

            print('\nA total of %d citing affiliations recorded.\n' % len(author_paper_affiliation_tuple_list))
            # Take unique tuples.
            author_paper_affiliation_tuple_list = list(set(author_paper_affiliation_tuple_list))

            # NOTE: Step 3. Clean the affiliation strings (optional, only used if taking the aggressive approach).
            if print_citing_affiliations:
                if affiliation_conservative:
                    print('Taking the conservative approach. Will not need to clean the affiliation names.')
                    print('List of all citing authors and affiliations:\n')
                else:
                    print('Taking the aggressive approach. Cleaning the affiliation names.')
                    print('List of all citing authors and affiliations before cleaning:\n')
                __print_author_and_affiliation(author_paper_affiliation_tuple_list)
            if not affiliation_conservative:
                cleaned_author_paper_affiliation_tuple_list = clean_affiliation_names(
                    author_paper_affiliation_tuple_list)
                if print_citing_affiliations:
                    print('List of all citing authors and affiliations after cleaning:\n')
                    __print_author_and_affiliation(cleaned_author_paper_affiliation_tuple_list)
                # Use the merged set to maximize coverage.
                author_paper_affiliation_tuple_list += cleaned_author_paper_affiliation_tuple_list
                # Take unique tuples.
                author_paper_affiliation_tuple_list = list(set(author_paper_affiliation_tuple_list))

            if cache_path is not None and len(author_paper_affiliation_tuple_list) > 0:
                save_cache(author_paper_affiliation_tuple_list, cache_path)
            print('Saved to cache: %s.\n' % cache_path)

            # NOTE: Step 4. Convert affiliations in plain text to Geocode.
            coordinates_and_info = affiliation_text_to_geocode(author_paper_affiliation_tuple_list)
            # Take unique tuples.
            coordinates_and_info = sorted(list(set(coordinates_and_info)))

            # NOTE: Step 5.1. Export csv file recording citation information.
            export_dict_to_csv(coordinates_and_info, csv_output_path)
            print('\nCitation information exported to %s.' % csv_output_path)

        else:
            # 直接用 csv
            coordinates_and_info = read_csv_to_dict(csv_output_path)
    finally:
        driver.quit()


    # NOTE: Step 5.2. Create the citation world map.
    citation_map = create_map(coordinates_and_info, pin_colorful=pin_colorful)
    citation_map.save(output_path)
    print('\nHTML map created and saved at %s.\n' % output_path)

    num_authors, num_affiliations, num_countries = count_citation_stats(coordinates_and_info)
    print('\nYou have been cited by %s researchers from %s affiliations and %s countries.\n' % (
        num_authors, num_affiliations, num_countries))
    return

