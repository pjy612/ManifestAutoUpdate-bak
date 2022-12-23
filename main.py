import git
import json
import time
import gevent
import logging
import argparse
import functools
import traceback
from pathlib import Path
from steam.enums import EResult
from multiprocessing.pool import ThreadPool
from multiprocessing.dummy import Pool, Lock
from DepotManifestGen.main import MySteamClient, MyCDNClient, get_manifest

lock = Lock()
parser = argparse.ArgumentParser()
parser.add_argument('-c', '--credential-location', default=None)
parser.add_argument('-l', '--level', default='INFO')
parser.add_argument('-p', '--pool-num', default=8)


class MyJson(dict):

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.load()

    def load(self):
        if not self.path.exists():
            return
        with self.path.open() as f:
            self.update(json.load(f))

    def dump(self):
        with self.path.open('w') as f:
            json.dump(self, f)


class LogExceptions:
    def __init__(self, fun):
        self.__callable = fun
        return

    def __call__(self, *args, **kwargs):
        try:
            return self.__callable(*args, **kwargs)
        except KeyboardInterrupt:
            raise
        except:
            logging.error(traceback.format_exc())


class ManifestAutoUpdate:
    log = logging.getLogger('ManifestAutoUpdate')
    ROOT = Path().absolute()
    users_path = ROOT / Path('users.json')
    app_info_path = ROOT / Path('appinfo.json')
    user_info_path = ROOT / Path('userinfo.json')
    account_info = MyJson(users_path)
    user_info = MyJson(user_info_path)
    app_info = MyJson(app_info_path)
    repo = git.Repo()
    app_lock = {}
    retry_num = 5
    remote_head = {}
    update_wait_time = 86400
    tags = set()

    def __init__(self, credential_location=None, level=None, pool_num=8):
        if level:
            level = logging.getLevelName(level.upper())
        else:
            level = logging.INFO
        logging.basicConfig(format='%(asctime)s - %(pathname)s[line:%(lineno)d] - %(levelname)s: %(message)s',
                            level=level)
        self.pool_num = pool_num
        self.credential_location = credential_location
        if not self.check_app_repo_local('app'):
            self.repo.git.fetch('origin', 'app:app')
        self.get_remote_tags()

    def get_manifest_callback(self, username, app_id, depot_id, manifest_gid, args):
        if not args.value:
            self.log.error(f'User {username}: get_manifest return {args.value.code.__repr__()}')
            return
        app_path = self.ROOT / f'depots/{app_id}'
        try:
            if args.value:
                self.set_depot_info(depot_id, manifest_gid)
                app_repo = git.Repo(app_path)
                with lock:
                    app_repo.git.add('-A')
                    app_repo.index.commit(f'Update depot: {depot_id}_{manifest_gid}')
                    app_repo.create_tag(f'{depot_id}_{manifest_gid}')
            elif app_path.exists():
                app_path.unlink(missing_ok=True)
        except Exception as e:
            logging.error(e)
        finally:
            with lock:
                if int(app_id) in self.app_lock:
                    self.app_lock[int(app_id)].remove(depot_id)
                    if int(app_id) not in self.user_info[username]['app']:
                        self.user_info[username]['app'].append(int(app_id))
                    if not self.app_lock[int(app_id)]:
                        self.log.debug(f'unlock app: {app_id}')
                        self.app_lock.pop(int(app_id))

    def set_depot_info(self, depot_id, manifest_gid):
        with lock:
            self.app_info[depot_id] = manifest_gid

    def save_user_info(self):
        with lock:
            self.user_info.dump()

    def save(self):
        self.save_depot()
        self.save_user_info()

    def save_depot(self):
        self.save_depot_info()

    def save_depot_info(self):
        with lock:
            self.app_info.dump()

    def get_app_worktree(self):
        worktree_dict = {}
        with lock:
            worktree_list = self.repo.git.worktree('list').split('\n')
        for worktree in worktree_list:
            path, head, name, *_ = worktree.split()
            name = name[1:-1]
            if not name.isdecimal():
                continue
            worktree_dict[name] = (path, head)
        return worktree_dict

    def get_remote_head(self):
        if self.remote_head:
            return self.remote_head
        head_dict = {}
        for i in self.repo.git.ls_remote('--head', 'origin').split('\n'):
            commit, head = i.split()
            head = head.split('/')[2]
            head_dict[head] = commit
        self.remote_head = head_dict
        return head_dict

    def check_app_repo_remote(self, app_id):
        return str(app_id) in self.get_remote_head()

    def check_app_repo_local(self, app_id):
        for branch in self.repo.heads:
            if branch.name == str(app_id):
                return True
        return False

    def get_remote_tags(self):
        if not self.tags:
            for i in self.repo.git.ls_remote('--tags').split('\n'):
                sha, tag = i.split()
                tag = tag.split('/')[-1]
                self.tags.add(tag)
        return self.tags

    def check_manifest_exist(self, depot_id, manifest_gid):
        for tag in set([i.name for i in self.repo.tags] + [*self.tags]):
            if f'{depot_id}_{manifest_gid}' == tag:
                return True
        return False

    def init_app_repo(self, app_id):
        app_path = self.ROOT / f'depots/{app_id}'
        if str(app_id) not in self.get_app_worktree():
            if app_path.exists():
                app_path.unlink(missing_ok=True)
            if self.check_app_repo_remote(app_id):
                with lock:
                    if not self.check_app_repo_local(app_id):
                        self.repo.git.fetch('origin', f'{app_id}:origin_{app_id}')
                self.repo.git.worktree('add', '-b', app_id, f'depots/{app_id}', f'origin_{app_id}')
            else:
                if self.check_app_repo_local(app_id):
                    self.log.warning(f'Branch {app_id} does not exist locally and remotely!')
                    self.repo.git.branch('-d', app_id)
                self.repo.git.worktree('add', '-b', app_id, f'depots/{app_id}', 'app')

    def retry(self, fun, *args, retry_num=-1, **kwargs):
        while retry_num:
            try:
                return fun(*args, **kwargs)
            except gevent.timeout.Timeout as e:
                retry_num -= 1
                self.log.warning(e)
            except Exception as e:
                self.log.error(e)
                return

    def get_manifest(self, username, password, sentry_name=None):
        with lock:
            if username not in self.user_info:
                self.user_info[username] = {}
                self.user_info[username]['app'] = []
            if 'update' not in self.user_info[username]:
                self.user_info[username]['update'] = 0
            if 'enable' not in self.user_info[username]:
                self.user_info[username]['enable'] = True
            if not self.user_info[username]['enable']:
                logging.warning(f'User {username} is disabled!')
                return
        if time.time() - self.user_info[username]['update'] < self.update_wait_time:
            logging.warning(f'User {username} has logged in today!')
            return
        sentry_path = None
        if sentry_name:
            sentry_path = Path(
                self.credential_location if self.credential_location else MySteamClient.credential_location) / sentry_name
        steam = MySteamClient(self.credential_location, sentry_path)
        steam.username = username
        result = steam.relogin()
        wait = 1
        if result != EResult.OK:
            self.log.error(f'User {username}: Relogin failure reason: {result.__repr__()}')
            if result == EResult.RateLimitExceeded:
                with lock:
                    time.sleep(wait)
            result = steam.login(username, password, steam.login_key)
        count = self.retry_num
        while result != EResult.OK:
            self.log.error(f'User {username}: Login failure reason: {result.__repr__()}')
            if result == EResult.RateLimitExceeded:
                if not count:
                    return
                with lock:
                    time.sleep(wait)
                result = steam.login(username, password, steam.login_key)
                wait += 1
                count -= 1
                continue
            elif result in (EResult.AccountLogonDenied, EResult.InvalidPassword, EResult.AccountDisabled,
                            EResult.AccountLoginDeniedNeedTwoFactor, EResult.PasswordUnset):
                logging.warning(f'User {username} has been disabled!')
                self.user_info[username]['enable'] = False
            return
        self.log.info(f'User {username} login successfully!')
        cdn = self.retry(MyCDNClient, steam, retry_num=self.retry_num)
        if not cdn:
            logging.error(f'User {username}: Failed to initialize cdn!')
            return
        app_id_list = []
        if cdn.packages_info:
            product_info = self.retry(steam.get_product_info, packages=cdn.packages_info, retry_num=self.retry_num)
            if not product_info:
                logging.error(f'User {username}: Failed to get package info!')
                return
            if cdn.packages_info:
                for package_id, info in product_info['packages'].items():
                    if 'depotids' in info and info['depotids'] and info['billingtype'] == 10:
                        app_id_list.extend(list(info['appids'].values()))
        if not app_id_list:
            self.user_info[username]['enable'] = False
            logging.warning(f'User {username} does not have any games and has been disabled!')
            return
        fresh_resp = self.retry(steam.get_product_info, app_id_list, retry_num=self.retry_num)
        if not fresh_resp:
            logging.error(f'User {username}: Failed to get app info!')
            return
        result_list = []
        flag = True
        for app_id in app_id_list:
            with lock:
                if int(app_id) in self.app_lock:
                    continue
                self.log.debug(f'lock app: {app_id}')
                self.app_lock[int(app_id)] = set()
            app = fresh_resp['apps'][app_id]
            if 'common' in app and app['common']['type'].lower() == 'game':
                for depot_id, depot in fresh_resp['apps'][app_id]['depots'].items():
                    with lock:
                        self.app_lock[int(app_id)].add(depot_id)
                    if 'manifests' in depot and 'public' in depot['manifests'] and int(
                            depot_id) in {*cdn.licensed_depot_ids, *cdn.licensed_app_ids}:
                        manifest_gid = depot['manifests']['public']
                        with lock:
                            if int(app_id) not in self.user_info[username]['app']:
                                self.user_info[username]['app'].append(int(app_id))
                            if self.check_manifest_exist(depot_id, manifest_gid):
                                self.log.warning(f'Already got the depot: {depot_id}')
                                continue
                        flag = False
                        job = gevent.Greenlet(
                            LogExceptions(lambda *args: (self.init_app_repo(args[1]), get_manifest(*args))[1]), cdn,
                            app_id, depot_id, manifest_gid, True, self.ROOT, 1)
                        job.rawlink(
                            functools.partial(self.get_manifest_callback, username, app_id, depot_id, manifest_gid))
                        job.start()
                        result_list.append(job)
                        gevent.idle()
            with lock:
                if int(app_id) in self.app_lock and not self.app_lock[int(app_id)]:
                    self.log.debug(f'unlock app: {app_id}')
                    self.app_lock.pop(int(app_id))
        with lock:
            if flag:
                self.user_info[username]['update'] = int(time.time())
        gevent.joinall(result_list)

    def run(self):
        if not self.account_info:
            return
        with Pool(self.pool_num) as pool:
            pool: ThreadPool
            result_list = []
            for username in self.account_info:
                password, sentry_name = self.account_info[username]
                result_list.append(
                    pool.apply_async(LogExceptions(self.get_manifest), (username, password, sentry_name)))
            try:
                while pool._state == 'RUN':
                    if all([result.ready() for result in result_list]):
                        self.log.info('The program is finished and will exit in 10 seconds!')
                        time.sleep(10)
                        break
                    self.save()
                    time.sleep(1)
            except KeyboardInterrupt:
                with lock:
                    pool.terminate()
            finally:
                self.save()


if __name__ == '__main__':
    args = parser.parse_args()
    ManifestAutoUpdate(args.credential_location, level=args.level,
                       pool_num=int(args.pool_num) if args.pool_num.isdecimal() else 8).run()
