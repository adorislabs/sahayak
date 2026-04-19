"""Bilingual response templates for CBC Part 5 — Conversational Interface.

Every user-facing string is defined here in both English and Hindi.
Templates use Python ``str.format()`` placeholders for dynamic values.
Hindi text is hand-authored for naturalness — not machine-translated.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Conversation state templates
# ---------------------------------------------------------------------------

GREETING: dict[str, str] = {
    "en": (
        "👋 Hello! I'm here to help you discover government welfare schemes you might be eligible for.\n\n"
        "Just tell me a bit about yourself in your own words — things like your age, where you live, "
        "what kind of work you do, and your household situation. The more you share, the better I can help.\n\n"
        "You can type in English or हिंदी — whichever is easier for you."
    ),
    "hi": (
        "👋 नमस्ते! मैं आपको सरकारी कल्याण योजनाएँ खोजने में मदद करने के लिए यहाँ हूँ।\n\n"
        "बस अपने बारे में बताइए — उम्र, कहाँ रहते हैं, क्या काम करते हैं, परिवार की स्थिति। "
        "जितना बताएँगे, उतना बेहतर मैं आपकी मदद कर पाऊँगा/पाऊँगी।\n\n"
        "हिंदी या English — जो आसान लगे, लिखें।"
    ),
}

GATHERING_ACK: dict[str, str] = {
    "en": (
        "Got it! Here's what I've picked up so far:\n{extracted_summary}\n\n"
        "A couple more things would really help me narrow down the right schemes for you:\n{questions}"
    ),
    "hi": (
        "समझ गया/गई! अब तक यह जानकारी मिली:\n{extracted_summary}\n\n"
        "आपके लिए सही योजनाएँ ढूँढने के लिए बस थोड़ी और जानकारी चाहिए:\n{questions}"
    ),
}

GATHERING_FIRST_ACK: dict[str, str] = {
    "en": (
        "Great, here's what I picked up from what you shared:\n\n"
        "{extraction_reasoning}\n\n"
        "If anything looks off, just correct it — otherwise, keep going and tell me more!"
    ),
    "hi": (
        "बढ़िया! आपने जो बताया उससे मैंने यह समझा:\n\n"
        "{extraction_reasoning}\n\n"
        "अगर कुछ गलत है तो सुधार दें — वरना आगे बताते रहें!"
    ),
}

CLARIFYING: dict[str, str] = {
    "en": (
        "Almost there! I just need a few more details to complete the picture:\n{questions}\n\n"
        "Feel free to skip anything by saying \"skip\" or \"not sure\"."
    ),
    "hi": (
        "लगभग हो गया! बस थोड़ी और जानकारी चाहिए:\n{questions}\n\n"
        "अगर कुछ पता नहीं, तो \"पता नहीं\" या \"छोड़ें\" कहें।"
    ),
}

MATCHING_STARTED: dict[str, str] = {
    "en": (
        "Perfect — I have enough to work with! Looking through all the schemes for you now... 🔍"
    ),
    "hi": (
        "बिल्कुल सही — मेरे पास काफ़ी जानकारी है! अभी सभी योजनाओं में आपकी पात्रता जाँच रहा/रही हूँ... 🔍"
    ),
}

PRESENTING_HEADER: dict[str, str] = {
    "en": "✅ Your Eligibility Report ({scheme_count} schemes checked)",
    "hi": "✅ आपकी पात्रता रिपोर्ट ({scheme_count} योजनाएँ जाँची गईं)",
}

EXPLORING_PROMPT: dict[str, str] = {
    "en": (
        "Would you like to:\n"
        "  • Type a scheme number for more details\n"
        "  • Ask \"what if\" to explore options "
        "(e.g., \"what if I opened a bank account?\")\n"
        "  • Type \"done\" to finish"
    ),
    "hi": (
        "आप क्या करना चाहेंगे:\n"
        "  • किसी योजना का नंबर लिखें — विस्तार से जानें\n"
        "  • \"अगर\" सवाल पूछें "
        "(जैसे, \"अगर मैं बैंक खाता खोल लूँ तो?\")\n"
        "  • \"बस\" लिखें — समाप्त करने के लिए"
    ),
}

ENDED: dict[str, str] = {
    "en": (
        "Thank you for using the CBC Scheme Checker! 🙏\n"
        "Remember: this is an indicative assessment. Please verify "
        "with your local government office before applying.\n\n"
        "Good luck with your applications!"
    ),
    "hi": (
        "CBC योजना जाँचकर्ता का उपयोग करने के लिए धन्यवाद! 🙏\n"
        "याद रखें: यह एक संकेतात्मक मूल्यांकन है। आवेदन करने से पहले "
        "अपने स्थानीय सरकारी कार्यालय से पुष्टि करें।\n\n"
        "आपके आवेदनों के लिए शुभकामनाएँ!"
    ),
}

# ---------------------------------------------------------------------------
# Follow-up question templates (ordered by impact)
# ---------------------------------------------------------------------------

FIELD_QUESTIONS: list[dict[str, str]] = [
    {
        "field": "applicant.age",
        "en": "How old are you?",
        "hi": "आपकी उम्र क्या है?",
        "schemes_affected": 15,
    },
    {
        "field": "location.state",
        "en": "Which state do you live in?",
        "hi": "आप किस राज्य में रहते हैं?",
        "schemes_affected": 15,
    },
    {
        "field": "household.income_annual",
        "en": "What is your family's approximate yearly income?",
        "hi": "आपके परिवार की लगभग सालाना आमदनी कितनी है?",
        "schemes_affected": 14,
    },
    {
        "field": "applicant.caste_category",
        "en": "Which community or category do you belong to? (e.g., SC, ST, OBC, General)",
        "hi": "आप किस जाति/वर्ग से हैं? (जैसे: SC, ST, OBC, सामान्य)",
        "schemes_affected": 12,
    },
    {
        "field": "applicant.gender",
        "en": "Could you tell me your gender?",
        "hi": "आपका लिंग क्या है?",
        "schemes_affected": 10,
    },
    {
        "field": "applicant.land_ownership_status",
        "en": "Do you own agricultural land?",
        "hi": "क्या आपके पास कृषि भूमि है?",
        "schemes_affected": 8,
    },
    {
        "field": "documents.aadhaar",
        "en": "Do you have an Aadhaar card?",
        "hi": "क्या आपके पास आधार कार्ड है?",
        "schemes_affected": 8,
    },
    {
        "field": "documents.bank_account",
        "en": "Do you have a bank account?",
        "hi": "क्या आपका बैंक खाता है?",
        "schemes_affected": 7,
    },
    {
        "field": "employment.type",
        "en": "What kind of work do you do? (farming, daily wage, salaried, self-employed, etc.)",
        "hi": "आप क्या काम करते हैं? (खेती, दिहाड़ी मज़दूरी, नौकरी, स्वरोज़गार, आदि)",
        "schemes_affected": 7,
    },
    {
        "field": "household.size",
        "en": "How many members are in your family?",
        "hi": "आपके परिवार में कितने सदस्य हैं?",
        "schemes_affected": 5,
    },
    {
        "field": "applicant.marital_status",
        "en": "What is your marital status?",
        "hi": "आपकी वैवाहिक स्थिति क्या है?",
        "schemes_affected": 4,
    },
    {
        "field": "household.bpl_status",
        "en": "Are you below the poverty line (BPL)?",
        "hi": "क्या आप गरीबी रेखा (BPL) से नीचे हैं?",
        "schemes_affected": 4,
    },
    {
        "field": "household.land_acres",
        "en": "How much land do you own? (in acres or bigha)",
        "hi": "आपके पास कितनी ज़मीन है? (एकड़ या बीघा में)",
        "schemes_affected": 3,
    },
    {
        "field": "applicant.disability_status",
        "en": "Do you have a disability?",
        "hi": "क्या आप दिव्यांग/विकलांग हैं?",
        "schemes_affected": 3,
    },
    {
        "field": "household.ration_card_type",
        "en": "What type of ration card do you have? (APL, BPL, Antyodaya, or none)",
        "hi": "आपके पास कौन सा राशन कार्ड है? (APL, BPL, अंत्योदय, या कोई नहीं)",
        "schemes_affected": 2,
    },
]

# Quick-lookup: field → question template
FIELD_QUESTION_MAP: dict[str, dict[str, str]] = {
    q["field"]: {"en": q["en"], "hi": q["hi"]}
    for q in FIELD_QUESTIONS
}

# ---------------------------------------------------------------------------
# Extraction reasoning / explainability templates
# ---------------------------------------------------------------------------

EXTRACTION_REASONING_HEADER: dict[str, str] = {
    "en": "I extracted the following from your message:",
    "hi": "आपके संदेश से मैंने यह जानकारी निकाली:",
}

EXTRACTION_ROW: dict[str, str] = {
    "en": '  • "{source_span}"  →  {field_label} = {value}  [{confidence}]',
    "hi": '  • "{source_span}"  →  {field_label} = {value}  [{confidence}]',
}

EXTRACTION_CONFIRM: dict[str, str] = {
    "en": "\nIs this correct? (Press Enter to continue, or correct anything.)",
    "hi": "\nक्या यह सही है? (जारी रखने के लिए Enter दबाएँ, या सुधारें।)",
}

# ---------------------------------------------------------------------------
# Contradiction resolution templates
# ---------------------------------------------------------------------------

CONTRADICTION_DIRECT: dict[str, str] = {
    "en": (
        "I noticed a discrepancy — earlier you said {field_label} is "
        "{existing_value}, but now you mentioned {new_value}. "
        "Which is correct?\n\n"
        "  1. {existing_value} (earlier)\n"
        "  2. {new_value} (just now)\n"
        "  3. Neither — let me give you the right answer"
    ),
    "hi": (
        "एक बात — पहले आपने {field_label} {existing_value} बताया था, "
        "लेकिन अभी {new_value} बताया। कौन सा सही है?\n\n"
        "  1. {existing_value} (पहले वाला)\n"
        "  2. {new_value} (अभी वाला)\n"
        "  3. दोनों नहीं — मैं सही बताता/बताती हूँ"
    ),
}

CONTRADICTION_RESOLVED: dict[str, str] = {
    "en": "Got it! I'll use {chosen_value} as your {field_label}.",
    "hi": "ठीक है! मैं {field_label} के लिए {chosen_value} रखता/रखती हूँ।",
}

CONTRADICTION_AUTO_RESOLVED: dict[str, str] = {
    "en": (
        "Note: I updated {field_label} from {old_value} to {new_value} "
        "based on your latest message. Let me know if that's wrong."
    ),
    "hi": (
        "ध्यान दें: मैंने {field_label} को {old_value} से {new_value} "
        "में बदल दिया है। अगर गलत है तो बताइए।"
    ),
}

# ---------------------------------------------------------------------------
# Correction templates
# ---------------------------------------------------------------------------

CORRECTION_ACK: dict[str, str] = {
    "en": (
        "Got it! I've updated your profile:\n"
        "  {field_label}: {old_value} → {new_value}\n\n"
        "Should I re-check your eligibility with this change?"
    ),
    "hi": (
        "ठीक है! मैंने आपकी जानकारी अपडेट कर दी:\n"
        "  {field_label}: {old_value} → {new_value}\n\n"
        "क्या इस बदलाव के साथ पात्रता दोबारा जाँचूँ?"
    ),
}

# ---------------------------------------------------------------------------
# "What If" templates
# ---------------------------------------------------------------------------

WHAT_IF_HEADER: dict[str, str] = {
    "en": '═══ "What If" Scenario: {description} ═══',
    "hi": '═══ "अगर ऐसा हो": {description} ═══',
}

WHAT_IF_IMPACT_POSITIVE: dict[str, str] = {
    "en": "📊 Impact: POSITIVE (+{count} scheme(s) gained)",
    "hi": "📊 प्रभाव: सकारात्मक (+{count} नई योजनाएँ)",
}

WHAT_IF_IMPACT_NEGATIVE: dict[str, str] = {
    "en": "📊 Impact: NEGATIVE ({count} scheme(s) lost)",
    "hi": "📊 प्रभाव: नकारात्मक ({count} योजनाएँ कम)",
}

WHAT_IF_IMPACT_NEUTRAL: dict[str, str] = {
    "en": "📊 Impact: No change to your eligibility.",
    "hi": "📊 प्रभाव: आपकी पात्रता में कोई बदलाव नहीं।",
}

WHAT_IF_SUGGESTION_HEADER: dict[str, str] = {
    "en": (
        "💡 Quick wins — things you could do to qualify for more schemes:\n"
    ),
    "hi": (
        "💡 आसान कदम — जो अपनाकर आप और योजनाओं के पात्र हो सकते हैं:\n"
    ),
}

# ---------------------------------------------------------------------------
# Result presentation templates
# ---------------------------------------------------------------------------

RESULT_ELIGIBLE_HEADER: dict[str, str] = {
    "en": "✅ ELIGIBLE ({count} scheme(s))",
    "hi": "✅ पात्र ({count} योजनाएँ)",
}

RESULT_NEAR_MISS_HEADER: dict[str, str] = {
    "en": "🔶 ALMOST ELIGIBLE ({count} scheme(s))",
    "hi": "🔶 लगभग पात्र ({count} योजनाएँ)",
}

RESULT_INELIGIBLE_HEADER: dict[str, str] = {
    "en": '❌ NOT ELIGIBLE ({count} scheme(s))  [Type "show ineligible" for details]',
    "hi": '❌ अपात्र ({count} योजनाएँ)  ["अपात्र दिखाएँ" लिखें — विवरण के लिए]',
}

RESULT_SCHEME_ROW: dict[str, str] = {
    "en": "  {index}. {scheme_name}  —  {confidence}% confidence",
    "hi": "  {index}. {scheme_name}  —  {confidence}% विश्वसनीयता",
}

RESULT_GAP_ROW: dict[str, str] = {
    "en": "     Gap: {gap_description}",
    "hi": "     कमी: {gap_description}",
}

NEXT_STEPS_HEADER: dict[str, str] = {
    "en": "📋 NEXT STEPS",
    "hi": "📋 अगले कदम",
}

DOCUMENTS_HEADER: dict[str, str] = {
    "en": "📄 DOCUMENTS NEEDED",
    "hi": "📄 ज़रूरी दस्तावेज़",
}

# ---------------------------------------------------------------------------
# Misc / error templates
# ---------------------------------------------------------------------------

SKIP_ACK: dict[str, str] = {
    "en": (
        "Sure, no worries! I'll mark that as unknown for now — "
        "some schemes might show as needing more info, but we can always fill it in later."
    ),
    "hi": (
        "ठीक है, कोई बात नहीं! मैं उसे अभी के लिए खाली छोड़ता/छोड़ती हूँ। "
        "बाद में बता सकते हैं।"
    ),
}

UNCLEAR_INPUT: dict[str, str] = {
    "en": (
        "Hmm, I didn't quite catch that — could you put it a different way? "
        "For example, you could mention your age, which state you're in, "
        "your income, or your type of work."
    ),
    "hi": (
        "हम्म, मुझे यह ठीक से समझ नहीं आया — क्या आप अलग तरह से बता सकते हैं? "
        "जैसे कि आपकी उम्र, राज्य, आमदनी, या काम।"
    ),
}

LLM_FALLBACK: dict[str, str] = {
    "en": "Let me ask you a few quick questions to understand your situation better.\n",
    "hi": "आइए, मैं आपसे कुछ सवाल पूछता/पूछती हूँ।\n",
}

ERROR_MATCHING: dict[str, str] = {
    "en": (
        "I ran into a small hiccup running the full eligibility check, "
        "but here's what I could find for you:"
    ),
    "hi": (
        "पात्रता जाँचते समय एक छोटी दिक्कत आई, "
        "लेकिन जो मैं ढूँढ पाया/पाई वह नीचे है:"
    ),
}

SESSION_EXPIRED: dict[str, str] = {
    "en": (
        "Your previous session has expired. Let's start fresh! "
        "Tell me about yourself."
    ),
    "hi": (
        "आपका पिछला सत्र समाप्त हो गया है। चलिए नए सिरे से शुरू करते हैं! "
        "अपने बारे में बताइए।"
    ),
}

# ---------------------------------------------------------------------------
# Confidence labels
# ---------------------------------------------------------------------------

CONFIDENCE_LABELS: dict[str, dict[str, str]] = {
    "HIGH": {"en": "High confidence", "hi": "उच्च विश्वसनीयता"},
    "MEDIUM": {"en": "Medium confidence", "hi": "मध्यम विश्वसनीयता"},
    "LOW": {"en": "Low confidence", "hi": "कम विश्वसनीयता"},
    "VERY_LOW": {"en": "Very low confidence", "hi": "बहुत कम विश्वसनीयता"},
}

CONFIDENCE_EXPLANATIONS: dict[str, dict[str, str]] = {
    "HIGH": {
        "en": "We're very confident you qualify.",
        "hi": "हमें पूरा भरोसा है कि आप पात्र हैं।",
    },
    "MEDIUM": {
        "en": "You likely qualify, but some details couldn't be fully verified.",
        "hi": "आप शायद पात्र हैं, लेकिन कुछ जानकारी पूरी तरह सत्यापित नहीं हुई।",
    },
    "LOW": {
        "en": "You may qualify, but there's significant uncertainty.",
        "hi": "आप पात्र हो सकते हैं, लेकिन काफ़ी अनिश्चितता है।",
    },
    "VERY_LOW": {
        "en": "We're not confident about this result. Please verify with the local office.",
        "hi": "इस परिणाम पर भरोसा कम है। कृपया स्थानीय कार्यालय से पुष्टि करें।",
    },
}

# ---------------------------------------------------------------------------
# Field labels (human-readable names for dot-path fields)
# ---------------------------------------------------------------------------

FIELD_LABELS: dict[str, dict[str, str]] = {
    "applicant.age": {"en": "Age", "hi": "उम्र"},
    "applicant.birth_year": {"en": "Birth year", "hi": "जन्म वर्ष"},
    "applicant.gender": {"en": "Gender", "hi": "लिंग"},
    "applicant.caste_category": {"en": "Caste/Category", "hi": "जाति/वर्ग"},
    "applicant.marital_status": {"en": "Marital status", "hi": "वैवाहिक स्थिति"},
    "applicant.disability_status": {"en": "Disability", "hi": "विकलांगता"},
    "applicant.disability_percentage": {"en": "Disability %", "hi": "विकलांगता %"},
    "applicant.land_ownership_status": {"en": "Land ownership", "hi": "भूमि स्वामित्व"},
    "location.state": {"en": "State", "hi": "राज्य"},
    "household.income_annual": {"en": "Annual income", "hi": "सालाना आमदनी"},
    "household.income_monthly": {"en": "Monthly income", "hi": "मासिक आमदनी"},
    "household.size": {"en": "Family size", "hi": "परिवार का आकार"},
    "household.bpl_status": {"en": "BPL status", "hi": "BPL स्थिति"},
    "household.ration_card_type": {"en": "Ration card", "hi": "राशन कार्ड"},
    "household.residence_type": {"en": "Residence type", "hi": "निवास प्रकार"},
    "household.land_acres": {"en": "Land (acres)", "hi": "ज़मीन (एकड़)"},
    "employment.type": {"en": "Occupation", "hi": "व्यवसाय"},
    "documents.aadhaar": {"en": "Aadhaar card", "hi": "आधार कार्ड"},
    "documents.bank_account": {"en": "Bank account", "hi": "बैंक खाता"},
    "documents.bank_account_type": {"en": "Bank account type", "hi": "खाता प्रकार"},
    "documents.mgnrega_job_card": {"en": "MGNREGA job card", "hi": "मनरेगा जॉब कार्ड"},
    "documents.caste_certificate": {"en": "Caste certificate", "hi": "जाति प्रमाण पत्र"},
    "documents.income_certificate": {"en": "Income certificate", "hi": "आय प्रमाण पत्र"},
}


# ---------------------------------------------------------------------------
# Helper function
# ---------------------------------------------------------------------------


def get_template(
    template_dict: dict[str, str],
    language: str,
    **kwargs: Any,
) -> str:
    """Retrieve and format a template in the given language.

    Falls back to English if the requested language is not available.

    Args:
        template_dict: A dict with ``"en"`` and ``"hi"`` keys.
        language: ``"en"``, ``"hi"``, or ``"hinglish"`` (uses ``"hi"``).
        **kwargs: Format parameters injected into the template string.

    Returns:
        Formatted template string.
    """
    lang_key = "hi" if language in ("hi", "hinglish") else "en"
    raw = template_dict.get(lang_key, template_dict.get("en", ""))
    if kwargs:
        try:
            return raw.format(**kwargs)
        except KeyError:
            # If formatting fails, return the raw template
            return raw
    return raw


def get_field_label(field_path: str, language: str) -> str:
    """Return the human-readable label for a field path.

    Falls back to the raw field path if no label is defined.
    """
    labels = FIELD_LABELS.get(field_path)
    if labels is None:
        return field_path
    lang_key = "hi" if language in ("hi", "hinglish") else "en"
    return labels.get(lang_key, labels.get("en", field_path))


def get_confidence_label(composite: float, language: str) -> str:
    """Map a numeric composite confidence to a human label."""
    if composite >= 0.85:
        tier = "HIGH"
    elif composite >= 0.70:
        tier = "MEDIUM"
    elif composite >= 0.50:
        tier = "LOW"
    else:
        tier = "VERY_LOW"
    return get_template(CONFIDENCE_LABELS[tier], language)
