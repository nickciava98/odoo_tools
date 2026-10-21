# odoo_tools

A small collection of general-purpose Odoo addons.

Branch `16.0` targets **Odoo 16 Community**.

| | Addon | Version | Summary |
| --- | --- | --- | --- |
| <img src="ai_base/static/description/icon.png" width="28"> | [`ai_base`](ai_base) | 16.0.1.0.0 | Shared connection to an OpenAI-compatible AI provider, used by the other AI addons |
| <img src="ai_text_rewrite/static/description/icon.png" width="28"> | [`ai_text_rewrite`](ai_text_rewrite) | 16.0.2.0.0 | Rewrite the content of char, text and html fields with an AI model, using a shared prompt set in Settings |

---

## ai_base

The connection to the AI provider, configured once and shared by `ai_text_rewrite` and
the `ai_chatbot` assistant (in the DueEsseTi Common repository): any endpoint speaking the OpenAI `/chat/completions` protocol
(Groq, OpenAI, OpenRouter, Ollama, LocalAI, Gemini's compatibility layer).

*Settings → General Settings → AI Provider*

| Setting | Parameter (`ir.config_parameter`) | Shipped default |
| --- | --- | --- |
| API base URL | `ai_base.base_url` | `https://api.groq.com/openai/v1` |
| API key | `ai_base.api_key` | *(empty — set your own)* |
| Model | `ai_base.model` | `openai/gpt-oss-120b` |
| Timeout (s) | `ai_base.timeout` | `60` |

Groq does not train on API data; the free tiers of some other providers do, so
check the provider's terms before pointing it at a production database. On the
Groq free tier every model is capped at **8,000 tokens per minute** (read from the
`x-ratelimit-limit-tokens` header in October 2026): enough for one person, not for
a team, which needs the paid Dev tier or another provider.

---

## ai_text_rewrite

<img src="ai_text_rewrite/static/description/icon.png" width="72" align="right" alt="">

Puts an **AI** button next to a field. Clicking it sends the current content to a
language model, which rewrites it following a system prompt configured once in
Settings — so every field in the database is rewritten with the same voice and
the same rules.

### Usage

The widget is opt-in: the button appears only where you declare it, and the stock
Odoo widgets are left untouched.

```xml
<field name="description" widget="ai_text"/>
<field name="comment" widget="ai_html"/>
```

| Widget | Field types | Renders as |
| --- | --- | --- |
| `ai_text` | `char`, `text` | a textarea, so long values wrap on several lines |
| `ai_html` | `html` | the standard wysiwyg editor, untouched |

`char` is supported on purpose: a plain `<input>` truncates a long value, while
the textarea wraps it. In list views `ai_text` keeps that wrapping instead of
cutting the value with an ellipsis, which is the behaviour `section_and_note_text`
is often borrowed for — so `ai_text` can replace it without changing how the
column reads. The button appears only on the row being edited, inline with the
value rather than above it.

The button opens a dialog holding an editable instruction, a preview of the
rewritten text and three actions — **Replace**, **Regenerate** and **Cancel**.
The field is written only when you confirm, so a bad result costs nothing.

### Configuration

*Settings → General Settings → AI Rewrite*

| Setting | Parameter (`ir.config_parameter`) | Shipped default |
| --- | --- | --- |
| Provider | `ai_text_rewrite.provider` | `openai` |
| System prompt | `ai_text_rewrite.system_prompt` | see below |

Endpoint, API key, model and timeout come from [`ai_base`](#ai_base). Out of the
box they point at [Groq](https://console.groq.com/keys), whose free tier is enough
to try it. Paste your key in Settings — never in the source tree. Upgrading from
16.0.1.x moves the values already set under `ai_text_rewrite.*` to `ai_base.*`.

Not every key is served every model: Groq answers `404 model_not_found` for a
model your key cannot reach, and the list a key actually has is at
`GET /openai/v1/models`. The module reports the provider's own explanation, so
that case reads as a wrong model rather than as a network failure.

### The shipped prompt

The default prompt is deliberately **general**: it improves how a text is written
without deciding what kind of text it is. Its core rule is to keep the shape of
the input — a label stays a one-line label with no final full stop, a sentence
stays a sentence, a paragraph stays a paragraph, HTML markup and list items are
preserved. A text that addresses a reader keeps its greeting, its closing and its
person; everything else stays impersonal and names an activity rather than
narrating it.

Two rules carry most of the weight. Nothing may be added that the input does not
say — no invented outcome, cause or duration, and no padding, because length is a
limit and not a target. And names, acronyms and figures are never swapped or
dropped, but their spelling, accents, apostrophes and capitalisation are always
corrected.

```
ho sistemato il bug delle griglie negli odv con lo sconto
    ->  Correzione del bug delle griglie negli OdV con lo sconto

<p>caratteristiche principali:</p><ul><li>batteria 5000mah</li></ul>
    ->  <p>Caratteristiche principali:</p><ul><li>Batteria 5000 mAh</li></ul>

buongiorno, le scrivo perche la fattura 1234 non e stata pagata
    ->  Buongiorno, le scrivo perché la fattura 1234 non è stata pagata
```

It is a default, not a fixture: rewrite it in Settings and the module will never
touch your version again — migrations only move a prompt that is still one this
module shipped.

### Providers

* **OpenAI-compatible endpoint** (default) — the one configured in `ai_base`.
* **Free service (no API key)** — [Pollinations](https://text.pollinations.ai),
  kept as a zero-configuration trial. It is anonymous and rate-limited — measured
  behaviour is `402` a little past 600 characters of prompt — so the module caps
  its own requests at 500 characters. Use it to see the feature work, not to run
  on it.

### Notes

* The rewritten text is produced by a third-party service: the field content
  leaves the Odoo instance. The dialog says so before anything is sent.
* Access requires `base.group_user`. Portal and public users cannot reach the
  endpoint, so the configured API key cannot be used as a free proxy.
* HTML answers are sanitised before they touch the field, and markdown fences the
  model may wrap around its answer are stripped.

---

## Tests

```bash
odoo-bin -d <database> -u ai_base,ai_text_rewrite --test-enable --test-tags /ai_base,/ai_text_rewrite --stop-after-init
```

`ai_base` 39, `ai_text_rewrite` 142 tests, including three browser
tours on the rewrite widgets and settings. No test reaches the network.

---

## License

[LGPL-3](LICENSE). Author: Niccolò Ciavarella.
