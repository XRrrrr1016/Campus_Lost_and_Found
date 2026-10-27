# HTTP JSON 接口

基础地址 `http://127.0.0.1:8000`。返回 `{"data": ...}`；异常 `{"error":{"message":"原因","request_id":"..."}}`。不使用前端传入的 user_id/role 鉴权。除登录外所有写接口需要会话 cookie 和 `X-CSRF-Token`，请求体 `Content-Type: application/json`，最大 800KB。

| 方法与路径 | 输入 | 输出与权限 |
| --- | --- | --- |
| GET /api/health | 无 | 服务状态、引擎版本 |
| GET /api/meta | 无 | 类别、AI 模式与版本 |
| GET /api/session | cookie 可选 | user 或 null、csrf |
| POST /api/login | username,password | user、csrf；Set-Cookie 保存会话，响应不含令牌 |
| POST /api/logout | `{}` | ok，删除会话并清 cookie |
| GET /api/items | q,kind,category,location,date_from,date_to,status,mine | 最多 500 条倒序；mine 仅本人；日期为区间重叠 |
| GET /api/items/:id | 无 | 单条详情，联系方式按权限裁剪 |
| POST /api/items | 下方字段 | 201，新记录；登录用户 |
| DELETE /api/items/:id | reason | 软删除、审计；本人/管理员，须为 open |
| POST /api/items/:id/matches | `{}` | 201，id/source_id/rule_version/engine_version/results；本人/管理员 |
| POST /api/items/:id/claims | answer,contact,note?,lost_item_id? | 201，申请 id/status/message；只能认领他人开放招领 |
| GET /api/claims | 无 | 本人提交或本人招领收到的申请；管理员全部 |
| POST /api/claims/:id/review | decision:approve/reject，note | 拾获者/管理员；驳回必填原因，批准要求特征正确 |
| POST /api/claims/:id/complete | `{}` | 拾获者/管理员；approved → completed、相关物品 resolved |
| GET /api/rules | 无 | 规则历史，最新在前 |
| POST /api/rules | name,weights | 201，追加版本；仅管理员 |
| GET /api/recommendations | 无 | 最近 100 次本人推荐历史；管理员全部 |
| POST /api/recommendations/:id/recompute | `{}` | 旧输入与旧规则重算，results、identical；生成者/管理员 |
| GET /api/audits | 无 | 最近 500 条审计；仅管理员 |

发布输入：

```json
{
  "kind": "found",
  "title": "图书馆拾到黑色卡包",
  "category": "证件",
  "date_from": "2026-10-25",
  "date_to": "2026-10-26",
  "location": "图书馆二楼",
  "color": "黑色",
  "description": "黑色卡包内有校园卡，请失主认领。",
  "contact": "finder@example.test",
  "secret_question": "内侧手写的两个字是什么？",
  "secret_answer": "向阳",
  "image": ""
}
```

`kind` 取 lost/found。招领必须包含秘密问题和答案；失物不保存这两个字段。支持类别：电子产品、证件、钥匙、雨伞、书籍、包袋、衣物、其他。图片为可选 `data:image/png;base64,...`（JPEG/WebP 同理），解码后 ≤500000 字节、检查魔数，禁止 SVG 和外链。

认领 `contact` 若省略，必须关联本人开放失物并使用其联系方式；前端为便于交接要求明确填写。答案经 NFKC、忽略大小写及空白后匹配。申请返回不提供正确/错误标志，防止即时试探；同一用户与物品仅能申请一次。核验者可看 `feature_matches`，申请者不输出该字段。通过前任何申请列表均不返回 applicant_contact。

权重示例：

```json
{"name":"更重视地点","weights":{"category":25,"location":30,"color":10,"time":10,"text":25}}
```

权重取 0–100 有限数，自动除以总和，缺少字段视为 0；至少一个大于 0。只有三项有效且启用的可比字段才输出非 insufficient 置信等级。

推荐结果的每一项包含 `candidate_id/title/score/confidence/fields/explanation`，所在批次包含 `rule_version`；可按批次 ID 复算。复算显示的是当时快照，如果当前物品已删除，点击原物品详情返回 404，但复算仍成功。
