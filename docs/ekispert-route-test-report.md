# 駅すぱあと 経路探索テスト報告書

検証日：2026-05-26

検証機：検証環境

サービス URL：

```text
http://<SERVER_IP_OR_FQDN>:4747
```

## 目的

駅すぱあと API が、東京側の大森から大阪側の谷町四丁目までの経路探索を正常に返却できることを確認する。

## 検証条件

出発地：

```text
大森(東京都)
station code: 22566
```

到着地：

```text
谷町四丁目
station code: 26032
```

実行 URL：

```text
http://<SERVER_IP_OR_FQDN>:4747/v1/xml/search/course/extreme?viaList=22566:26032
```

## 駅コード確認

大森確認：

```bash
curl 'http://localhost:4747/v1/xml/station?name=%E5%A4%A7%E6%A3%AE'
```

結果：

```text
<Station code="22566"><Name>大森(東京都)
```

谷町四丁目確認：

```bash
curl 'http://localhost:4747/v1/xml/station?name=%E8%B0%B7%E7%94%BA%E5%9B%9B%E4%B8%81%E7%9B%AE'
```

結果：

```text
<Station code="26032"><Name>谷町四丁目
```

## 経路探索結果

経路探索 API は `Course` を返却した。第一候補の概要は以下。

```text
大森(東京都)
ＪＲ京浜東北線・大宮行
品川
ＪＲ新幹線のぞみ
新大阪
OsakaMetro御堂筋線・天王寺行
梅田(地下鉄)
徒歩(同駅)
東梅田
OsakaMetro谷町線・八尾南行
谷町四丁目
```

主要値：

```text
transferCount="3"
timeOnBoard="158"
FareSummary Oneway 9150
```

## 判定

大森(東京都) から 谷町四丁目 までの経路探索は正常に完了した。

## インストール成功判定への組み込み

本テストはインストール成功判定テストの一部として扱う。期待結果は以下。

```text
HTTP 応答が XML であること
ResultSet に engineVersion が含まれること
Course が返却されること
出発地に 大森(東京都) が含まれること
到着地に 谷町四丁目 が含まれること
```

保存ログ：

```text
/opt/ekispert-install/logs/course-omori-tanimachi4-20260526092105.xml
```


