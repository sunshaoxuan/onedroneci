# 駅すぱあと Linux インストール検証環境記録

検証日：2026-05-26

検証機：検証環境

ホスト名：`PHREKI`

ログインユーザー：`phr`

公式情報：

- インストールマニュアル：`http://dl.ekispert.com/webservice/install_manual_linux.html`
- 最新版インストーラ：`http://dl.ekispert.com/webservice/download`
- 改訂情報：`https://ekiworld.net/support/index.html`

## 検証結論

RHEL 8 検証機で、ダウンロード、インストール、アンインストール、アップデート、外部アクセス、経路探索を確認済み。検証結果は合格。

本検証で取得したファイル：

```text
exp-web-service-20260601_4796-linux_x86_64.tar.gz
```

サービス名は `eeed`、待受ポートは `4747`。

## 検証機環境

| 項目 | 状態 | 判定 |
| --- | --- | --- |
| OS | Red Hat Enterprise Linux 8.10 | 合格 |
| アーキテクチャ | x86_64 | 合格 |
| CPU | 約 5GHz | 合格 |
| メモリ | 673MiB | 推奨未満だが検証は合格 |
| ディスク | `/`、`/opt`、`/usr/local`、`/var` の空き約 36GB | 合格 |
| sudo | `phr` が実行可能 | 合格 |
| ダウンロードサイト | `dl.ekispert.com` に接続可能 | 合格 |
| サービス | `eeed` | 稼働中 |
| 待受 | `0.0.0.0:4747` | 合格 |
| ファイアウォール | `4747/tcp` を開放済み | 合格 |
| 自動起動 | `chkconfig eeed on` | 合格 |

## 実インストール結果

インストール先：

```text
/usr/local/ekispert
```

設定ファイル：

```text
/etc/eeed.conf
```

起動スクリプト：

```text
/etc/init.d/eeed
```

ログディレクトリ：

```text
/var/log/ekispert
```

作業ディレクトリ：

```text
/opt/ekispert-install/
```

SHA256：

```text
0b82a2b19dcb5d54d974980a9959813e5dd9393bd0cc51f8733eee3fc500ca08
```

データバージョン：

```text
engineVersion="202606_01a"
apiVersion="1.27.0.0"
知識ベース 20260601
鉄道時刻表 20260601
JR 20260601
私鉄 20260520
```

## アクセス方法

検証機内：

```text
http://localhost:4747/v1/xml/dataversion
```

外部端末：

```text
http://<SERVER_IP_OR_FQDN>:4747/v1/xml/dataversion
```

東京から新宿の経路探索：

```text
http://<SERVER_IP_OR_FQDN>:4747/v1/xml/search/course/extreme?viaList=22828:22741
```

## スクリプト検証結果

| スクリプト | コマンド概要 | 結果 |
| --- | --- | --- |
| `ekispert_uninstall.sh` | `sudo bash ... --lang ja --keep-kit` | 合格 |
| `ekispert_install.sh` | `sudo bash ... --lang ja --package ...tar.gz` | 合格 |
| `ekispert_update.sh` | `sudo bash ... --lang ja --package ...tar.gz` | 合格 |

アップデート検証では同一バージョンのインストーラを更新ファイルとして使用し、停止、バックアップ、削除、再インストール、起動、dataversion、東京から新宿の経路探索を確認した。

## 顧客本番参考

顧客本番 `upds-eki01` の調査結果：

| 項目 | 状態 | 判定 |
| --- | --- | --- |
| OS | Red Hat Enterprise Linux 9.7 | 合格 |
| アーキテクチャ | x86_64 | 合格 |
| CPU | Intel Xeon Gold 6542Y、最大 2.9GHz、2 vCPU | 合格 |
| メモリ | 7.5GiB | 合格 |
| ディスク | `/`、`/usr/local`、`/var`、`/opt` の空き 63GB | 合格 |

顧客本番は検証機よりリソースが多く、導入先として十分な条件を満たす。オンラインダウンロード可否は顧客ネットワークの出口制御に依存する。


