# 駅すぱあと Linux インストール手順書

対象：導入担当者から提供された Linux 版最新版インストーラ

検証済みインストーラ：

```text
exp-web-service-20260601_4796-linux_x86_64.tar.gz
```

検証済み環境の例：

```text
<SERVER_IP_OR_FQDN>
Red Hat Enterprise Linux 8.10
```

顧客環境で実施する場合は、以下の値を現地値に置き換える。

```text
<SERVER_IP_OR_FQDN>  サーバーの IP アドレスまたは FQDN
<SSH_USER>           作業ユーザー
<INSTALL_PACKAGE>    インストーラ tar.gz
```

公式情報：

- インストールマニュアル：`http://dl.ekispert.com/webservice/install_manual_linux.html`
- 最新版インストーラ：`http://dl.ekispert.com/webservice/download`
- 改訂情報：`https://ekiworld.net/support/index.html`

検証結果：インストール、アンインストール、アップデート、外部アクセス、経路探索の動作を確認済み。
配布キットのルートディレクトリで `sudo bash scripts/ekispert_install.sh` と `sudo bash scripts/ekispert_update.sh` を実行し、`--package` 指定なしでインストーラを自動検出できることも確認済み。

## 1. 自動化スクリプト

配布パッケージには以下の Red Hat 系 Linux 用スクリプトを含める。

```text
scripts/ekispert_install.sh
scripts/ekispert_update.sh
scripts/ekispert_uninstall.sh
```

共通仕様：

- 表示言語は `--lang ja|zh|en` で指定する。既定値は日本語。
- 環境確認で不足がある場合は警告としてログへ記録し、処理は継続する。
- 実行ごとに独立したログファイルを生成する。
- 画面には進捗と最終結果のみを表示する。
- `/etc/init.d` が存在しない環境では自動作成する。
- `libjson-c.so` が不足し、`/usr/lib64/libjson-c.so.5` が存在する場合は自動リンクする。
- サービス起動後、`4747` が LISTEN になるまで待機してから検証する。
- 既定ポートは公式既定の `4747`。`--port 80` を指定した場合は 80 番の使用状況を確認し、使用中なら `4747` に自動で戻す。

インストール：

```bash
sudo bash scripts/ekispert_install.sh
```

アップデート：

```bash
sudo bash scripts/ekispert_update.sh
```

ZIP を任意の場所へ展開し、展開ディレクトリへ移動して実行する。スクリプトは自身の場所からキットのルートを判定し、`files/packages` 配下のインストーラを自動検出する。

```bash
cd ekispert-install-kit-20260601
sudo bash scripts/ekispert_install.sh
```

`scripts` ディレクトリへ移動してから実行することもできる。

```bash
cd ekispert-install-kit-20260601/scripts
sudo bash ekispert_install.sh
```

インストーラを明示したい場合のみ `--package` を指定する。

```bash
sudo bash scripts/ekispert_install.sh --package files/packages/exp-web-service-20260601_4796-linux_x86_64.tar.gz
```

80 番ポートで起動したい場合は `--port 80` を指定する。80 番が既に使用中の場合、スクリプトは警告をログに記録し、公式既定の 4747 番で起動する。

```bash
sudo bash scripts/ekispert_install.sh --port 80
```

アンインストール：

```bash
sudo bash scripts/ekispert_uninstall.sh
```

作業ディレクトリを残す場合：

```bash
sudo bash scripts/ekispert_uninstall.sh --keep-kit
```

## 2. 事前確認

ログイン：

```bash
ssh <SSH_USER>@<SERVER_IP_OR_FQDN>
```

環境確認：

```bash
cat /etc/redhat-release
uname -m
lscpu
free -h
df -h / /opt /usr/local /var
sudo -v
```

確認結果の目安：

- OS が Red Hat Enterprise Linux または AlmaLinux 系であること。
- アーキテクチャが `x86_64` であること。
- `/opt`、`/usr/local`、`/var` に十分な空き容量があること。
- 作業ユーザーが sudo を実行できること。

## 3. ダウンロード確認

```bash
curl -I -L --connect-timeout 10 http://dl.ekispert.com/webservice/download
curl -I -L --connect-timeout 10 http://dl.ekispert.com/webservice/install_manual_linux.html
curl -I -L --connect-timeout 10 https://ekiworld.net/support/index.html
```

本検証時の `download` の遷移先：

```text
/webservice/exp-web-service-20260601_4796-linux_x86_64.tar.gz
```

導入担当者からはログイン認証不要と連絡あり。将来、登録番号、パスワード、CD キー、シリアル番号、ライセンスファイルの入力が必要になった場合は、認可された担当者が入力する。ログと手順書には完全な認証情報を記録しない。

## 4. 作業ディレクトリ

```bash
sudo mkdir -p /opt/ekispert-install/{packages,updates,logs,archive,work}
sudo chown -R phr:phr /opt/ekispert-install
sudo chmod 700 /opt/ekispert-install
```

用途：

- `packages`：初回インストール用ファイルを保存する。
- `updates`：更新用ファイルを保存する。
- `logs`：インストール、起動、検証ログを保存する。
- `archive`：アップデートごとのバックアップと検証結果を保存する。
- `work`：展開後の作業ディレクトリとして使用する。

## 5. インストーラ取得と校正

```bash
cd /opt/ekispert-install/packages
curl -L --fail --connect-timeout 15 --max-time 1800 \
  -o exp-web-service-20260601_4796-linux_x86_64.tar.gz \
  http://dl.ekispert.com/webservice/download

sha256sum exp-web-service-20260601_4796-linux_x86_64.tar.gz \
  | tee /opt/ekispert-install/logs/package-sha256-$(date +%Y%m%d).txt
```

検証済み SHA256：

```text
0b82a2b19dcb5d54d974980a9959813e5dd9393bd0cc51f8733eee3fc500ca08
```

## 6. 手動インストール

```bash
cd /opt/ekispert-install/work
rm -rf exp-web-service
tar xzf /opt/ekispert-install/packages/exp-web-service-20260601_4796-linux_x86_64.tar.gz
cd exp-web-service
chmod 755 install.sh
sudo bash ./install.sh --install_path /usr/local/ekispert \
  2>&1 | tee /opt/ekispert-install/logs/install-$(date +%Y%m%d%H%M%S).log
```

正常終了時の出力：

```text
ekispert install successfully !!
```

生成物確認：

```bash
ls -ld /usr/local/ekispert /etc/eeed.conf /etc/init.d/eeed /var/log/ekispert
```

## 7. 起動、自動起動、ファイアウォール

サービス起動：

```bash
sudo service eeed start
sudo service eeed status
```

ポート確認：

```bash
ss -ltnp | grep ':4747'
```

自動起動：

```bash
sudo chkconfig --add eeed
sudo chkconfig eeed on
chkconfig --list eeed
```

期待値：

```text
eeed  0:off  1:off  2:on  3:on  4:on  5:on  6:off
```

外部アクセス用ポート開放。既定は `4747/tcp`。`--port 80` を指定し、80 番で起動した場合は `80/tcp` を開放する。

```bash
sudo firewall-cmd --permanent --add-port=4747/tcp
sudo firewall-cmd --reload
```

## 8. アクセス確認

サーバー内：

```bash
curl http://localhost:4747/v1/xml/dataversion
```

外部端末：

```text
http://<SERVER_IP_OR_FQDN>:4747/v1/xml/dataversion
```

東京から新宿の経路探索：

```text
http://<SERVER_IP_OR_FQDN>:4747/v1/xml/search/course/extreme?viaList=22828:22741
```

## 9. インストール成功判定テスト

以下の全項目が合格した場合に、インストール成功と判定する。

| No | 実行場所 | コマンド | 期待結果 |
| --- | --- | --- | --- |
| 1 | サーバー | `sudo service eeed status` | `Running EEE list:` と PID が表示される |
| 2 | サーバー | `ss -ltnp \| grep ':4747'` | `0.0.0.0:4747` が `LISTEN` で表示される |
| 3 | サーバー | `curl -sS http://localhost:4747/v1/xml/dataversion` | XML が返り、`apiVersion="1.27.0.0"` と `engineVersion="202606_01a"` を含む |
| 4 | サーバー | `curl -sS http://$(hostname -I \| awk '{print $1}'):4747/v1/xml/dataversion` | No.3 と同等の XML が返る |
| 5 | 別端末 | `curl -sS http://<SERVER_IP_OR_FQDN>:4747/v1/xml/dataversion` | No.3 と同等の XML が返る |
| 6 | サーバーまたは別端末 | `curl -sS 'http://<SERVER_IP_OR_FQDN>:4747/v1/xml/search/course/extreme?viaList=22828:22741'` | XML が返り、`<Course`、`<Name>東京</Name>`、`<Name>新宿</Name>` を含む |
| 7 | サーバーまたは別端末 | `curl -sS 'http://<SERVER_IP_OR_FQDN>:4747/v1/xml/search/course/extreme?viaList=22566:26032'` | XML が返り、`<Course`、`<Name>大森(東京都)</Name>`、`<Name>谷町四丁目</Name>` を含む |

別端末から No.5 以降が失敗し、サーバー内の No.3 と No.4 が成功する場合は、アプリケーションではなくネットワークまたはファイアウォールの問題として切り分ける。

代表的な確認コマンド：

```bash
sudo firewall-cmd --list-ports
sudo firewall-cmd --list-all
```

`4747/tcp` が表示されない場合は以下を実行する。

```bash
sudo firewall-cmd --permanent --add-port=4747/tcp
sudo firewall-cmd --reload
```

## 10. 実行効果と校正一覧

| 工程 | コマンド | 正常時の効果 | 校正方法 |
| --- | --- | --- | --- |
| ログイン | `ssh <SSH_USER>@<SERVER_IP_OR_FQDN>` | 対象サーバーへログイン | `hostname` を確認 |
| sudo | `sudo -v` | エラーなし | sudo コマンドが実行可能 |
| OS | `cat /etc/redhat-release` | RHEL バージョン表示 | 導入先の対応 OS を確認 |
| アーキテクチャ | `uname -m` | `x86_64` | インストーラ名と一致 |
| ダウンロード | `curl -L --fail ...` | tar.gz 生成 | 約 474MB |
| ハッシュ | `sha256sum ...` | SHA256 出力 | 本手順書の値と一致 |
| 展開 | `tar xzf ...` | `exp-web-service` 生成 | `install.sh` の存在確認 |
| インストール | `sudo bash ./install.sh ...` | 成功メッセージ表示 | 生成物の存在確認 |
| 起動 | `sudo service eeed start` | `[OK]` 表示 | `service eeed status` で PID 表示 |
| ポート | `ss -ltnp | grep ':4747'` | `0.0.0.0:4747` 表示 | LISTEN 状態 |
| dataversion | `curl .../dataversion` | XML 応答 | `engineVersion="202606_01a"` を確認 |
| 経路探索 | `curl ...search/course/extreme...` | `Course` 応答 | 経路結果を確認 |

## 11. 検証済み結果

| 項目 | 結果 |
| --- | --- |
| 最新版インストーラ取得 | 合格 |
| 自動インストールスクリプト | 合格 |
| アンインストールスクリプト | 合格 |
| アップデートスクリプト | 合格 |
| `--package` 指定なしの自動検出 | 合格 |
| `scripts` ディレクトリ内からの実行 | 合格 |
| RHEL 9.7 での `/etc/init.d` 不在対応 | 合格 |
| RHEL 9.7 での `libjson-c.so` 不足対応 | 合格 |
| `eeed` 起動 | 合格 |
| `0.0.0.0:4747` LISTEN | 合格 |
| 外部 dataversion | 合格 |
| 東京から新宿の経路探索 | 合格 |
| 大森(東京都)から谷町四丁目の経路探索 | 合格 |

バージョン情報：

```text
apiVersion="1.27.0.0"
engineVersion="202606_01a"
知識ベース 20260601
鉄道時刻表 20260601
JR 20260601
私鉄 20260520
```

## 12. アップデート手順

定期更新はメール通知を契機に実施する。

1. `https://ekiworld.net/support/index.html` を開く。
2. 右側の `駅すぱあと改訂情報` 最新分を確認する。
3. ファイル名、サイズ、バージョン、改訂内容を確認する。
4. `http://dl.ekispert.com/webservice/download` から最新版を取得する。
5. 更新ファイルと SHA256 を保存する。

更新ファイルを配置：

```bash
mkdir -p /opt/ekispert-install/updates
cp <新しいインストーラ>.tar.gz /opt/ekispert-install/updates/
```

アップデートスクリプト実行：

```bash
sudo bash scripts/ekispert_update.sh \
  --package /opt/ekispert-install/updates/<新しいインストーラ>.tar.gz
```

アップデートスクリプトは以下を作成する。

```text
/opt/ekispert-install/logs/update-YYYYMMDDhhmmss.log
/opt/ekispert-install/archive/YYYYMMDDhhmmss/
```

アーカイブには更新ファイル SHA256、更新前 dataversion、更新後 dataversion、旧設定、旧起動スクリプト、旧ログを保存する。

## 13. アンインストール方針

完全削除：

```bash
sudo bash scripts/ekispert_uninstall.sh
```

作業ディレクトリを残す場合：

```bash
sudo bash scripts/ekispert_uninstall.sh --keep-kit
```

削除対象：

- `/usr/local/ekispert`
- `/etc/eeed.conf`
- `/etc/init.d/eeed`
- `/var/log/ekispert`
- `eeed` PID
- `chkconfig` 登録
- `firewalld` の `4747/tcp`
- `/opt/ekispert-install`

