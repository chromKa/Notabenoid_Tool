import math
from multiprocessing import Pool

import requests
from bs4 import BeautifulSoup

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 '
                  'YaBrowser/23.1.3.949 Yowser/2.5 Safari/537.36',
}
session = requests.Session()
url_main = 'http://notabenoid.org/'
data = {
    'login[login]': '',
    'login[pass]': '',
}
result = session.post(url_main, headers=headers, data=data, verify=False)


def refresh_post(count_id_urls, session_post, url_book, id_url_str):
    data_post = {
        'Orig[ord]': count_id_urls,

    }
    session_post.post(url_book + '/' + id_url_str + '/edit', headers=headers, data=data_post, verify=False)


def refresh_post_pool(dic_post):
    # all_ids.append({data_id: [count_id_urls, session_post, url_book, arr_ids]})
    print(dic_post)
    for key in dic_post:
        arr_data = dic_post[key]
        count_id_urls = arr_data[0]+(key*50)
        for id_str in arr_data[3]:
            refresh_post(count_id_urls, arr_data[1], arr_data[2], id_str)
            print(count_id_urls, arr_data[1], arr_data[2], id_str)
            count_id_urls += 1


def create_list_ids(url_parce, session_post):
    page = session_post.get(url_parce, headers=headers)
    while page.status_code != 200:
        page = session_post.get(url_parce, headers=headers)
    soup = BeautifulSoup(page.text, "html.parser")
    number_chapter_id = []
    # add title
    number_chapter = soup.find_all('tr')
    for i_nc in number_chapter:
        number_chapter_id.append(i_nc.get('id'))

    number_chapter_id.remove(None)
    number_chapter_id_str = []
    for i_nc_id in number_chapter_id:
        temp_str = str(i_nc_id)
        number_chapter_id_str.append(temp_str.replace("o", ""))
    if len(number_chapter_id_str) > 0:
        return number_chapter_id_str
    else:
        return []


def last_page(session_post, url_book):
    page = session_post.get(url_book, headers=headers)

    while page.status_code != 200:
        page = session_post.get(url_book, headers=headers)
    soup = BeautifulSoup(page.text, "html.parser")
    number_chapter = soup.find_all('ul', class_='selectable')
    np = []
    for i in number_chapter:
        np = (i.find_all('a'))
    if len(np) > 0:
        return np[-1].get_text()
    else:
        return 1


def get_ids(dic_make):
    print(dic_make)
    for key in dic_make:
        data_ids = create_list_ids(key, dic_make[key])
        return data_ids


def refresh_id1(count_t, url_book, session_post):
    try:
        page_last_number = int(last_page(session_post, url_book))
        int_url_id = math.ceil(int(count_t) / 50)
        count_id_urls = int_url_id * 50 - 49

        range_url_ids = page_last_number - int_url_id

        all_url_for_ids = []

        for i in range(range_url_ids + 1):
            url_parce = url_book + '?Orig_page=' + str(i + int_url_id)

            all_url_for_ids.append(url_parce)

        data_pool = []
        for site in all_url_for_ids:
            data_pool.append({site: session_post})

        with Pool(10) as p:
            data_ids = p.map(get_ids, data_pool)
        #
        # for arr_ids in data_ids:
        #     for id_post in arr_ids:
        #         print(id_post, count_id_urls)
        #         refresh_post(count_id_urls, session_post, url_book, id_post)
        #         count_id_urls += 1

        all_ids = []

        for data_id, arr_ids in enumerate(data_ids):
            all_ids.append({data_id: [count_id_urls, session_post, url_book, arr_ids]})

        print(all_ids)
        for i in all_ids:
            refresh_post_pool(i)
        # with Pool(20) as p:
        #     p.map(refresh_post_pool, all_ids)

    except Exception:
        ...


refresh_id1(1, 'http://notabenoid.org/book/85408/577930', session)
