# GitLab読取専用とHelp SQL生成物ポリシー

## 毎回の上流同期とローカル適合
- Help構築を選択した各実行では、Cache判定より先に選択Branchの最新Commitを明示RefspecでFetchする。取得失敗時は停止し、保存済みZIPへ退避しない。
- Gitの差分転送を利用しながら、取得したCommitの追跡ファイル全体をCheckoutする。追加・変更・削除を反映し、Sparse Checkoutは拒否する。「最新」はFetchが取得した選択Branchの先端を意味する。
- 構築ログに前回Commit、今回Commit、変更パス、SVN Revision、ローカルポリシーSHA256、Cache Keyを記録する。
- ローカル適合は自有ツールのHELP_SQL_POLICYで保持する。Helpの上流Checkout内で手編集された追跡ファイル又は新規未追跡ファイルを検出した場合、上書きせず停止する。必要な編集は担当者が自有ツールの構築ポリシーへ移して検証する。自動Stash・自動Mergeは行わない。
- node_modules、.ci-cache、.cacheは生成Cacheとして扱う。未追跡の任意ファイルを削除するgit cleanは使用しない。
- SVN文書もCache判定前に同期する。明示されたSVN Revisionは利用者指定を維持する。Git Commit・SVN Revision・依存定義・ローカルポリシーが一致する場合だけ既存ZIPを再利用する。

## 同期強化の受入記録（2026-09-20）
| 要求 | 成果物・証拠 |
| --- | --- |
| 最新の完全な上流取得 | HELP_SOURCE_SYNC。実Gitの2版で追加・変更・削除と再実行を検証 |
| ローカル適合の保持 | 同期後にHELP_SQL_POLICYを適用する試験合格。追跡編集・新規ファイルは保全して停止 |
| 古いCacheへの退避禁止 | 遠隔取得失敗の異常終了と、Git/SVN同期がCache判定より前であることを検証 |
| 関連回帰 | test_help_sql_policy.py / test_build_console.py、47件合格 |
| 構築VM | 実上流の全追跡パス一致・反復同期・新旧生成器の単一SQL ZIP試験合格 |
| 配置 | server.py SHA256: 9f193722e7f15a0e3d2e5b4cdcb0120ecc60fe804014b0306aa1d2e24f4be619。systemd active、8090の/api/builds応答確認 |
| GitLab読取専用 | 遠隔先端50624a1adbfbec490c4e15d27b3dbe3a56428d3fを確認。書込みなし |

この同期強化の配置前バックアップは /opt/ohr-build-console/validation/help-upstream-sync-20260920/server.before.py。顧客本番の全体構築は利用者が実行するため今回未実施。検証は隔離fixtureと構築器稼働確認の範囲である。


## 適用範囲
GitLabの製品開発リポジトリは管理者権限にかかわらず読取専用とする。Commit、Push、MR作成・Merge、Branch・Tag変更は禁止する。取得・参照を行い、必要な構築適合は自有ツール及び生成物に保持する。上流取消しは開発担当者が行う。

## 原因と取消し範囲
ohr-help-docs/release_ci の 32182154cacf0e2459e05ae0a81aeae425102dc5 は scripts/generateInsertSQL.js と scripts/generateInsertSQL.test.js を変更した。現在の先端50624a1adbfbec490c4e15d27b3dbe3a56428d3fには後続の開発変更がある。履歴の巻戻し・強制Pushは行わない。
限定した逆Patchを D:/workspace/codex-logs/gitlab-readonly-help-20260920/revert-32182154.patch に作成し、先端でgit apply --checkが成功した。これは遠隔取消し実施の証拠ではない。GitLabへの適用と提出は開発担当者の作業として残る。

## 構築処理
build-console/server.pyのHELP_SQL_POLICYが生成物のみを扱う。
1. npm run build前にdocs/build内の旧Help SQL生成物を除去する。追跡ファイルとsymlinkは変更せずエラーにする。
2. ビルド後、`insert_ohr_help_default.sql` の存在を確認し、feature別のSQLを統合せず維持する。単一の旧形式又はdefaultの欠落は停止する。
3. 元のnpm run bundleにfeature別SQLを渡す。標準交付ではdefaultだけをtenantに配置し、その他はohr向け任意資材とREADMEへ分離する。
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
