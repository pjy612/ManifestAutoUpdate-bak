# Steam 清单仓库

## 项目简介

* 使用`Actions`自动获取`Steam`清单

## 项目结构

* `data`分支: 用于存放账号数据,第一次运行程序初始化后会自动将其签出到`data`目录
    * `data/client`: 用于存放账号凭证文件和`cm`服务器信息的目录,需要将账号`ssfn`文件放在该目录
    * `data/users.json`: 用于存放账号和密码
        * 格式为: `{"账号": ["密码", "ssfnxxxx"], "账号": ["密码", null], ...}`
        * 没有`ssfn`需要填`null`
    * `data/appinfo.json`: 用于存放`appid`对应的`清单id`
        * 格式为: `{"11111": "清单id", ...}`
    * `data/userinfo.json`: 用于存放账户拥有的`appid`信息和是否被禁用等信息
        * 格式为: `{"账号": {"app": [11111, 22222, ...], "update": 1673018145, "enable": true, "status": 63}, ...}`
            * `update`: 上次更新时间戳
            * `enable`: 是否被禁用
            * `status`: 登录失败的原因 - [EResult](https://partner.steamgames.com/doc/api/steam_api#EResult)
    * `data/.gitattributes`: 记录`git-crypt`需要加密的文件
        * 默认内容: `users.json filter=git-crypt diff=git-crypt`
* 以`appid`为名称的分支: 改分支用于存放清单和密钥文件
    * `depots/xxx`: 程序运行后如果该`app`有新的清单会从远程拉取对应`appid`分支,不存在则会使用`main`分支的第一次提交创建一个空的`appid`分支,使用`worktree`
      将其签出到`depots/对应appid分支`目录,例如`depots/11111`
        * `depots/xxx/仓库id_清单id.manifest`: 清单文件
        * `config.vdf`: 密钥文件,其格式参考`Steam/config/config.vdf`
            * ```vdf
              "depots"
              {
                  "仓库id"
                  {
                      "DecryptionKey" "仓库密钥"
                  }
              }
              ```
* `tag`: 标记每一个的清单的提交
    * 命名格式: `仓库id_清单id`
    * 用于过滤已爬取的清单

## 运行流程

1. `.github/workflows/CI.yml`
    * 使用`Actions`定期爬取清单
2. 开启多线程同时登录多个账号爬取清单,直到所有账号都被爬取完毕
    * 判断账号是否禁用
    * 判断账号距离上次爬取时间是否大于可爬取间隔
    * 获取账号所有可爬取的清单，使用`tag`过滤已爬取的清单
3. 爬取结束后调用`push.py`上传`分支`和`tag`,并推送`data`分支

## 如何部署

1. fork本仓库
2. 安装git,并配置你的`github`账号
3. 克隆你fork的仓库
    * `git clone https://github.com/你的名称/ManifestAutoUpdate --recurse-submodules --depth=1`
        * `--recurse-submodules`: 克隆子模块
        * `--depth=1`: 浅克隆
4. 安装依赖
    * `pip install -r requirements.txt`
5. 参数
    * `-c, --credential-location`: 存放账户凭据的路径,默认为`data/client`
    * `-l, --level`: 日志等级,默认为`INFO`
    * `-p, --pool-num`: 同时爬取账号数量,默认为`8`
    * `-r, --retry-num`: 失败或超时重试次数,默认为`3`
    * `-t, --update-wait-time`: 账号再次爬取间隔时间,单位秒,默认`86400`
    * `-k, --key`: 用于`users.json`解密的密钥
        * 提交远程仓库后如果重新克隆需要指定密钥才能解密
        * 手动解密: 把密钥保存到`KEY`文件,安装`git-crypt`,切换到data分支运行命令`git-crypt unlock KEY`
6. 运行程序
    * `python main.py`
7. 初始化
    * 第一次运行程序会进行初始化操作
    * 初始化会生成`data`分支,使用`worktree`签出到`data`目录
    * 生成密钥用于加密`users.json`
        * 密钥生成路径位于: `data/KEY`
        * 同时程序会输出密钥的十六进制字符串,需要将其存放到github仓库密钥,名称保存为`KEY`
            * 打开你的仓库 -> `Settings` -> `Secrets` -> `Actions` -> `New repository secret`
            * 或者在你的仓库地址后面加上`/settings/secrets/actions/new`
    * 增加账号密码到`data/users.json`:
        * 之后如果需要使用`Actions`需要将其推送到远程仓库
            * 再次运行程序,程序结束时会自动推送到`data`分支
            * 手动推送步骤如下:
                1. `cd data`: 切换到`data`目录
                2. `git add -u`: 增加修改的内容
                3. `git commit -m "update"`: 提交修改
                4. `git push origin data`: 推送到远程`data`分支

## 如何pr清单
* 本项目使用`Actions`定期检查并合并清单，是否合并成功请在`Actions`运行完后查看对应分支
1. 完成部署本项目并爬取清单
2. 打开你要`pr`清单的分支，点击`Compare & pull request`
3. 点击`Create pull request`创建`pr`