from bs4 import BeautifulSoup

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 '
                  'YaBrowser/23.1.3.949 Yowser/2.5 Safari/537.36',
}


def get_all_translates(url, session_get):
    html = session_get.get(url, headers=headers)
    count_tem = 0
    while html.status_code != 200:
        html = session_get.get(url, headers=headers)
        if count_tem == 10:
            return None
        count_tem += 1
    soup = BeautifulSoup(html.text, 'html.parser')
    ids_trans = create_list_ids_trans_replace(soup)
    list_ids_original = create_list_ids_replace(soup)
    if list_ids_original == 'error' or ids_trans == 'error':
        return None
    ids_line_origin = {}
    count_id = 0
    count_id_trans = 0
    number_chapter = soup.find_all('tbody')[0].findAll('tr')
    for im in number_chapter:
        tt = im.find(class_='t').find_all('p', class_='text')

        str_and_id = {}
        all_str_dic = []
        if len(tt) > 1:
            all_t = im.find(class_='t').findAll(class_='text')
            for t in all_t:
                str_and_id[ids_trans[count_id_trans]] = t.text

                count_id_trans += 1
            all_str_dic.append(str_and_id)
        else:
            if tt:
                str_and_id[ids_trans[count_id_trans]] = tt[0].text
                count_id_trans += 1
                all_str_dic.append(str_and_id)
            else:
                str_and_id[ids_trans[count_id_trans]] = ''
                count_id_trans += 1
                all_str_dic.append(str_and_id)

        ids_line_origin[list_ids_original[count_id]] = all_str_dic
        count_id += 1
    return ids_line_origin


def create_list_ids_replace(soup):
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
        return 'error'


def create_list_ids_trans_replace(soup):
    number_chapter_id = []
    # add title
    number_chapter = soup.find_all('td', class_='t')

    for i_nc in number_chapter:
        t = i_nc.find_all('div')
        if t:
            for i_inc in t:
                p = i_inc.get('id')
                if p:
                    number_chapter_id.append(p)
        else:
            number_chapter_id.append('')

    number_chapter_id_str = []
    for i_nc_id in number_chapter_id:
        temp_str = str(i_nc_id)
        number_chapter_id_str.append(temp_str.replace("t", ""))

    if len(number_chapter_id_str) > 0:
        return number_chapter_id_str
    else:
        return 'error'


def make_all(dic_make):
    # print(dic_make)
    for key in dic_make:
        data = get_all_translates(key, dic_make[key])
        return data
