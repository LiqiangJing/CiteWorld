from citation_map_webdriver import generate_citation_map_selenium

if __name__ == '__main__':
    # Replace this with your Google Scholar ID.
    scholar_id = 'j8xkbCIAAAAJ'
    generate_citation_map_selenium(scholar_id=scholar_id, chromedriver="chromedriver-mac-arm64/chromedriver")

    # generate_citation_map_selenium(scholar_id, parse_csv=True)
    # generate_citation_map(scholar_id,
    #                       output_path='citation_map.html',
    #                       csv_output_path='citation_info.csv',
    #                       parse_csv=False,
    #                       cache_folder='cache',
    #                       affiliation_conservative=True,
    #                       num_processes=16,
    #                       use_proxy=False,
    #                       pin_colorful=True,
    #                       print_citing_affiliations=True)
