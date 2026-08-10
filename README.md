# Keepa GPT Bridge v1

この中継APIは、KeepaのPrivate API keyをCustom GPTへ直接見せずにKeepaへ問い合わせるためのものです。

## Renderでの設定
環境変数を2つ設定します。

- KEEPA_API_KEY = KeepaのPrivate API access key
- ACTION_API_KEY = 自分で作る長いランダム文字列（GPT Action → この中継APIの認証用）

ACTION_API_KEYはKeepaキーとは別物です。例としてパスワード管理アプリ等で32文字以上のランダム値を作ってください。

## GPT Action側
1. `openapi_schema.yaml` の `YOUR-RENDER-APP` を実際のRender URLに置換。
2. GPT Actionsの認証を「APIキー」にする。
3. 認証方式を「カスタムヘッダー」にする。
4. ヘッダー名を `X-Action-Key` にする。
5. キー値にRender側と同じ ACTION_API_KEY を入れる。
6. スキーマ欄に `openapi_schema.yaml` を貼る。

Keepa Private API keyそのものはGPT Actionsには入れません。
