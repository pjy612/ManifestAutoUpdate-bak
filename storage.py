import os
import vdf
import time
import winreg
import sqlite3
import requests
import traceback
from pathlib import Path
from multiprocessing.pool import ThreadPool
from multiprocessing.dummy import Pool, Lock

lock = Lock()


def get(sha, path):
    url_list = [f'https://cdn.jsdelivr.net/gh/{repo}@{sha}/{path}',
                f'https://ghproxy.com/https://raw.githubusercontent.com/{repo}/{sha}/{path}']
    retry = 3
    while True:
        for url in url_list:
            try:
                r = requests.get(url)
                if r.status_code == 200:
                    return r.content
            except requests.exceptions.ConnectionError:
                print(f'获取清单失败: {path}')
                retry -= 1
                if not retry:
                    print(f'超过最大重试次数: {path}')
                    raise


def get_manifest(sha, path, steam_path: Path):
    try:
        if path.endswith('.manifest'):
            save_path = steam_path / 'depotcache' / path
            if save_path.exists():
                with lock:
                    print(f'已存在清单: {path}')
                return
            content = get(sha, path)
            with lock:
                print(f'清单下载成功: {path}')
            with save_path.open('wb') as f:
                f.write(content)
        elif path == 'config.vdf':
            content = get(sha, path)
            with lock:
                print(f'密钥下载成功: {path}')
            depots_config = vdf.loads(content.decode())
            if depotkey_merge(steam_path / 'config' / path, depots_config):
                print('合并config.vdf成功')
            if stool_add([depot_id for depot_id in depots_config['depots']]):
                print('导入steamtools成功')
    except KeyboardInterrupt:
        raise
    except:
        traceback.print_exc()
        raise
    return True


def depotkey_merge(config_path, depots_config):
    if not config_path.exists():
        with lock:
            print('config.vdf不存在')
        return
    with open(config_path) as f:
        config = vdf.load(f)
    config['InstallConfigStore']['Software']['Valve']['Steam']['depots'].update(depots_config['depots'])
    with open(config_path, 'w') as f:
        vdf.dump(config, f, pretty=True)
    return True


def stool_add(depot_id_list):
    info_path = Path('~/AppData/Roaming/Stool/info.pak').expanduser()
    conn = sqlite3.connect(info_path)
    c = conn.cursor()
    for depot_id in depot_id_list:
        c.execute(f'insert or replace into Appinfo (appid,type) values ({depot_id},1)')
    conn.commit()
    return True


def get_steam_path():
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam')
    steam_path = Path(winreg.QueryValueEx(key, 'SteamPath')[0])
    return steam_path


def main(app_id):
    url = f'https://api.github.com/repos/{repo}/branches/{app_id}'
    r = requests.get(url)
    if 'commit' in r.json():
        sha = r.json()['commit']['sha']
        url = r.json()['commit']['commit']['tree']['url']
        r = requests.get(url)
        if 'tree' in r.json():
            stool_add([app_id])
            result_list = []
            with Pool(32) as pool:
                pool: ThreadPool
                for i in r.json()['tree']:
                    result_list.append(pool.apply_async(get_manifest, (sha, i['path'], get_steam_path())))
                try:
                    while pool._state == 'RUN':
                        if all([result.ready() for result in result_list]):
                            break
                        time.sleep(0.1)
                except KeyboardInterrupt:
                    with lock:
                        pool.terminate()
                    raise
            if all([result.successful() for result in result_list]):
                print(f'入库成功: {app_id}')
                print('重启steam生效')
                return True
    print(f'入库失败: {app_id}')
    return False


repo = 'wxy1343/ManifestAutoUpdate'

if __name__ == '__main__':
    try:
        main(input('appid: '))
    except KeyboardInterrupt:
        exit()
    except:
        traceback.print_exc()
    os.system('pause')
