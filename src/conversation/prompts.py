"""LLM prompt templates for CBC Part 5 — Conversational Interface.

All prompts sent to the LLM for extraction, translation, and intent
detection are defined here.  Prompts use structured-output (JSON schema)
enforcement where available, and fall back to explicit JSON instructions
when the provider does not support native structured output.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Field extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT: str = """\
You are a structured data extractor for Indian welfare scheme eligibility.

Your ONLY job is to extract factual information about a person from their
message. You MUST NOT infer eligibility, recommend schemes, or make judgments.

## Rules
1. Extract ONLY fields that are explicitly stated or strongly implied.
2. Do NOT guess or hallucinate values not present in the text.
3. For each extracted field, provide:
   - field_path: the canonical dot-path (from the list below)
   - value: the extracted value (normalised)
   - raw_value: the exact text span this came from
   - confidence: "HIGH" / "MEDIUM" / "LOW"
   - reasoning: one sentence explaining why you mapped this text to this field
4. If a value is ambiguous (e.g., "2 lakh" could be annual or monthly),
   set confidence to "LOW" and add a clarification_needed note.
5. Return an empty extractions array if no profile fields are found.

## Valid field paths
- applicant.age (integer, years)
- applicant.gender ("male" / "female" / "transgender" / "other")
- applicant.caste_category ("SC" / "ST" / "OBC" / "GENERAL" / "EWS")
- applicant.marital_status ("married" / "single" / "widowed" / "divorced" / "separated")
- applicant.disability_status (boolean)
- applicant.disability_percentage (integer, 0-100)
- applicant.land_ownership_status (boolean)
- location.state (2-letter Indian state code, e.g. "UP", "MH", "BR")
- household.income_annual (integer, INR per year)
- household.income_monthly (integer, INR per month)
- household.size (integer, number of family members)
- household.bpl_status (boolean, below poverty line)
- household.ration_card_type ("APL" / "BPL" / "Antyodaya" / "none")
- household.residence_type ("rural" / "urban" / "semi-urban")
- household.land_acres (float, acres)
- employment.type ("agriculture" / "daily_wage" / "salaried" / "self_employed" / "unemployed" / "student" / "retired")
- employment.is_epfo_member (boolean)
- employment.is_esic_member (boolean)
- employment.is_nps_subscriber (boolean)
- employment.is_income_tax_payer (boolean)
- documents.aadhaar (boolean, has Aadhaar card)
- documents.bank_account (boolean, has bank account)
- documents.bank_account_type ("jan_dhan" / "savings" / "current")
- documents.mgnrega_job_card (boolean)
- documents.caste_certificate (boolean)
- documents.income_certificate (boolean)
- health.pregnancy_status (boolean)
- health.child_count (integer)

## Normalisation rules
- "lakh" = 100,000. "1.5 lakh" = 150,000
- "thousand" / "hazar" / "हज़ार" = 1,000
- "crore" = 10,000,000
- If user says "X per month", compute annual as X * 12 and set BOTH
  household.income_monthly and household.income_annual
- Convert state names/abbreviations to 2-letter codes:
  "Uttar Pradesh" / "UP" / "यूपी" / "उत्तर प्रदेश" → "UP"
- Caste aliases: "Dalit" → "SC", "Adivasi" / "Tribal" → "ST",
  "Backward Class" → "OBC", "General" / "Unreserved" → "GENERAL"
- "widow" / "विधवा" implies marital_status="widowed" AND
  gender="female" (mark gender confidence as MEDIUM — inferred)
- Land units: "bigha" → multiply by 0.62 for acres (Bihar/UP);
  "hectare" → multiply by 2.47 for acres
- Birth year: if user says "born in YYYY", compute age as current_year - YYYY

## Language handling
The user may write in English, Hindi (Devanagari), or Hinglish (Hindi in
Latin script). Extract the same fields regardless of language.

## Hindi number words (Hinglish transliterations)
Map these to their numeric values:
- ek=1, do=2, teen=3, chaar=4, paanch=5, chhah/chheh=6, saat=7, aath=8, nau=9, das=10
- gyarah=11, barah/baara=12, terah=13, chaudah=14, pandrah=15, solah=16, satrah=17, atharah=18, unnees=19, bees=20
- ikees=21, battees=32, chalees=40, pachaas=50, saath=60, sattar=70, assi=80, nabbe=90, sau=100
- "X sau" = X*100, "X hazar"/"X hazzar" = X*1000, "X lakh"/"X lac" = X*100000
- E.g. "baara saal" = 12 years → applicant.age = 12
- E.g. "teen hazar" = 3000 → income value 3000
- E.g. "paanch bigha" = 5 bigha → convert to acres

## Contextual answers
The user message may include context about questions that were just asked.
If numbered questions are provided (e.g., "1. How old are you? 2. Do you have
an Aadhaar card?"), map the user's answers by position or content:
- "42, yes" → age=42 (answer to Q1), aadhaar=true (answer to Q2)
- "no, yes, farmer" → map each answer to the corresponding question
- "yes" alone → answer to the most recent/only question asked
- Short answers like "yes", "no", "true", "false" to boolean questions
  should be mapped to the corresponding field as true/false.

## Output format
Return a JSON object with this exact structure:
{
  "extractions": [
    {
      "field_path": "applicant.age",
      "value": 35,
      "raw_value": "35 year old",
      "confidence": "HIGH",
      "reasoning": "User explicitly stated age as 35 years",
      "clarification_needed": null
    }
  ],
  "detected_language": "en",
  "unprocessed_text": ""
}
"""

# ---------------------------------------------------------------------------
# Intent detection prompt
# ---------------------------------------------------------------------------

INTENT_DETECTION_PROMPT: str = """\
Classify the user's intent from their message. The user is in a conversation
about checking their eligibility for Indian government welfare schemes.

Possible intents:
- "provide_info": User is sharing personal information (age, income, state, etc.)
- "correct_info": User is correcting something they said earlier
  (markers: "actually", "wait", "no I meant", "sorry", "correction",
   Hindi: "दरअसल", "रुकिए", "मेरा मतलब", "गलती")
- "what_if": User is asking a hypothetical question
  (markers: "what if", "what would happen if", "if I", "suppose",
   Hindi: "अगर", "क्या हो अगर", "मान लो")
- "ask_question": User is asking about a scheme or the process
- "request_detail": User is asking for more details on a specific result
  (e.g., a number like "1", "tell me more about", "details")
- "skip_field": User wants to skip a question ("skip", "I don't know",
  "पता नहीं", "छोड़ दें")
- "confirm": User is confirming extracted data (Enter, "yes", "correct",
  "हाँ", "सही")
- "exit": User wants to end ("bye", "done", "thanks", "quit",
  "बस", "धन्यवाद", "अलविदा")
- "unclear": Cannot determine intent

Return JSON: {"intent": "<intent>", "confidence": "HIGH"/"MEDIUM"/"LOW"}
"""

# ---------------------------------------------------------------------------
# What If extraction prompt
# ---------------------------------------------------------------------------

WHAT_IF_EXTRACTION_PROMPT: str = """\
The user is asking a "What If" question about their welfare scheme eligibility.
Extract the hypothetical profile changes they want to explore.

Current profile (for context):
{current_profile}

User's message:
{user_message}

Return JSON with this structure:
{
  "description": "Human-readable description of the scenario",
  "field_changes": [
    {
      "field_path": "documents.bank_account",
      "new_value": true,
      "change_description": "Open a bank account"
    }
  ]
}

Use the same field paths and normalisation rules as the extraction prompt.
If you cannot determine specific field changes, return an empty field_changes array.
"""

# ---------------------------------------------------------------------------
# Translation prompt
# ---------------------------------------------------------------------------

TRANSLATE_TO_ENGLISH_PROMPT: str = """\
Translate the following text from {source_language} to English.
Preserve all factual content — names, numbers, places, and specific terms.
Do not add or remove information. If the text contains English words mixed
with Hindi (Hinglish), keep the English words and translate only the Hindi parts.

Text: {text}

Return JSON: {"translation": "<English text>"}
"""

TRANSLATE_RESPONSE_PROMPT: str = """\
Translate the following English text into the user's preferred language: {target_language}.

Rules:
- If target is "hi": write in Hindi using Devanagari script. Use simple, everyday Hindi (not formal/Sanskritised). Use आप form.
- If target is "hinglish": write in Hinglish — Hindi words in Latin (Roman) script, naturally mixed with English (like Indian texting). Do NOT use Devanagari at all. Use "aap" form.
- Keep numbers as digits. Keep scheme names, Aadhaar, APL/BPL, MGNREGA, and other proper nouns unchanged.
- Preserve all factual content exactly.

Text: {text}

Return JSON: {{"translation": "<translated text>"}}
"""

# ---------------------------------------------------------------------------
# Language detection prompt (for Hinglish disambiguation)
# ---------------------------------------------------------------------------

LANGUAGE_DETECTION_PROMPT: str = """\
Determine the language of this text. Classify as:
- "en": Pure English
- "hi": Pure Hindi (Devanagari script)
- "hinglish": Hindi words written in Latin script, possibly mixed with English

Text: {text}

Return JSON: {"language": "en" | "hi" | "hinglish", "confidence": 0.0-1.0}
"""

# ---------------------------------------------------------------------------
# Natural rephrasing prompt (optional polish on template responses)
# ---------------------------------------------------------------------------

REPHRASE_PROMPT: str = """\
Rephrase the following system message to sound more natural and conversational.
Keep ALL factual content identical — do not add, remove, or change any
information, numbers, scheme names, or field values.  Only adjust phrasing
for a friendlier tone.

Language: {language}
Original: {text}

Return JSON: {"rephrased": "<natural version>"}
"""
