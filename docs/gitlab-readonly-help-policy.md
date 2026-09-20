# GitLab読取専用とHelp SQL生成物ポリシー

## 適用範囲
GitLabの製品開発リポジトリは管理者権限にかかわらず読取専用とする。Commit、Push、MR作成・Merge、Branch・Tag変更は禁止する。取得・参照を行い、必要な構築適合は自有ツール及び生成物に保持する。上流取消しは開発担当者が行う。

## 原因と取消し範囲
ohr-help-docs/release_ci の 32182154cacf0e2459e05ae0a81aeae425102dc5 は scripts/generateInsertSQL.js と scripts/generateInsertSQL.test.js を変更した。現在の先端50624a1adbfbec490c4e15d27b3dbe3a56428d3fには後続の開発変更がある。履歴の巻戻し・強制Pushは行わない。
限定した逆Patchを D:/workspace/codex-logs/gitlab-readonly-help-20260920/revert-32182154.patch に作成し、先端でgit apply --checkが成功した。これは遠隔取消し実施の証拠ではない。GitLabへの適用と提出は開発担当者の作業として残る。

## 構築処理
build-console/server.pyのHELP_SQL_POLICYが生成物のみを扱う。
1. npm run build前にdocs/build内の旧Help SQL生成物を除去する。追跡ファイルとsymlinkは変更せずエラーにする。
2. ビルド後、租戸別SQLの内容を変更せず単一insert_ohr_help.sqlへ統合する。単一出力だけの場合はそのまま使用する。出力なし又は単一・分割の混在は停止する。
3. 元のnpm run bundleに単一SQLを渡す。
4. ポリシー本文のSHA256をHelp Cache Keyに加える。ポリシー変更後に古いCacheを再使用しない。
5. Help checkoutのorigin.pushurlをdisabled://gitlab-read-onlyに設定する。これはローカル設定であり、遠隔権限の変更ではない。明示URL等を含む全経路を技術的に禁止する保証ではなく、永続作業規則も適用する。

## 検証
- test_help_sql_policy.py と test_build_console.py: 46件合格。WindowsではBASH_EXEにGit Bashの絶対パスを指定する。
- 構築VM上で3218215の親版と現在版の実生成器・実bundlerを使用した隔離試験に成功。両版とも単一SQL、2件のINSERT、日本語・引用符を保持したZIPを生成した。
- 上流スクリプトの試験前後のバイト一致、稼働Help checkoutの追跡差分が空であること、Bash構文を確認した。
- 構築器配置前に進行中Jobがないことを確認。server.pyだけを更新し、設定・認証情報・ポートは保持した。systemdのactiveと配置ハッシュ一致を確認した。
- 配置SHA256: 8bdae33496504801b65aafb39ef512bc413977ea5a353cb2f769b40d94236780。
- GitLab先端は配置後も50624a1adbfbec490c4e15d27b3dbe3a56428d3f。今回GitLabへの書込みなし。
- 顧客全体の構築・実DBへのHelp登録は実施していない。

## 受入と残作業
| 項目 | 状態 |
| --- | --- |
| 永続のGitLab読取専用規則 | ユーザー規則及びOneOps規則へ反映 |
| ローカル生成物戦略 | 実装・46試験・構築VMの両版ZIP試験合格 |
| 稼働構築器への反映 | 配置ハッシュ・active・GitLab不変を確認 |
| 上流取消し | 逆Patchの事前検査まで。開発担当者による適用が必要 |

## 回復
稼働構築器の変更前ファイルは /opt/ohr-build-console/validation/gitlab-readonly-help-20260920/server.before.py。
戻す場合は現在の配置ハッシュと差分を再確認し、server.pyだけを復元してサービスを再起動する。上流Git履歴とDBは変更しない。
