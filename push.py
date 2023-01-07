import os
import git
import time
import traceback
from multiprocessing.pool import ThreadPool
from multiprocessing.dummy import Pool, Lock

lock = Lock()


def push(repo=git.Repo()):
    app_sha = None
    remote_head_list = []
    remote_tag_list = []
    for i in repo.git.ls_remote('origin').split('\n'):
        sha, refs = i.split()
        if refs.startswith('refs/heads/'):
            head = refs.split('/')[2]
            if head.isdecimal():
                remote_head_list.append((sha, head))
            elif head == 'app':
                app_sha = sha
        elif refs.startswith('refs/tags/'):
            tag = refs.split('/')[2]
            remote_tag_list.append((sha, tag))
    total_branch = 0
    total_tag = 0
    with Pool(8) as pool:
        pool: ThreadPool
        result_list = []
        for local_head in repo.heads:
            if local_head.name.isdecimal():
                for remote_sha, remote_head in remote_head_list:
                    if local_head.name == remote_head and local_head.commit.hexsha == remote_sha:
                        break
                else:
                    if local_head.commit.hexsha == app_sha:
                        continue
                    total_branch += 1
                    with lock:
                        print(local_head.name, local_head.commit.hexsha)
                    result_list.append(pool.map_async(os.system, ('git push origin ' + local_head.name,)))
        for local_tag in repo.tags:
            for remote_sha, remote_tag in remote_tag_list:
                if remote_tag == local_tag.name:
                    break
            else:
                total_tag += 1
                with lock:
                    print(local_tag.name, local_tag.commit.hexsha)
                result_list.append(pool.map_async(os.system, ('git push origin ' + local_tag.name,)))
        try:
            while pool._state == 'RUN':
                if all([result.ready() for result in result_list]):
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            with lock:
                pool.terminate()
    print(f'Pushed {total_branch} branch!')
    print(f'Pushed {total_tag} tag!')
    if not all([result.successful() for result in result_list]):
        return push(repo=repo)


def push_data(repo=None):
    if not repo:
        repo = git.Repo('data')
    print('Pushing to the data branch!')
    try:
        repo.git.add('client/ssfn*')
    except git.exc.GitCommandError:
        pass
    try:
        repo.git.add('appinfo.json', 'userinfo.json', 'users.json')
        repo.git.commit('-m', 'update')
    except git.exc.GitCommandError:
        pass
    try:
        repo.git.push('origin', 'data')
    except git.exc.GitCommandError:
        traceback.print_exc()


if __name__ == '__main__':
    push()
    push_data()
