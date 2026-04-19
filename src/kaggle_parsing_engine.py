"""
Kaggle Indian Government Schemes Parsing Engine
Converts raw eligibility text into DMN-compatible JSON rules (Tier-3)
"""

import csv
import json
import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== ENUMS & CONSTANTS ====================

STATE_CODES = {
    "andhra pradesh": "AP",
    "assam": "AS",
    "bihar": "BR",
    "chhattisgarh": "CG",
    "delhi": "DL",
    "goa": "GA",
    "gujarat": "GJ",
    "haryana": "HR",
    "himachal pradesh": "HP",
    "jharkhand": "JH",
    "karnataka": "KA",
    "kerala": "KL",
    "madhya pradesh": "MP",
    "maharashtra": "MH",
    "manipur": "MN",
    "meghalaya": "ML",
    "mizoram": "MZ",
    "nagaland": "NL",
    "odisha": "OD",
    "punjab": "PB",
    "rajasthan": "RJ",
    "sikkim": "SK",
    "tamil nadu": "TN",
    "telangana": "TS",
    "uttar pradesh": "UP",
    "uttarakhand": "UK",
    "west bengal": "WB",
}

CANONICAL_FIELDS = {
    "age": "applicant.age",
    "gender": "applicant.gender",
    "caste": "applicant.caste_category",
    "disability": "applicant.disability_status",
    "disability_percentage": "applicant.disability_percentage",
    "marital_status": "applicant.marital_status",
    "education": "applicant.education_level",
    "enrolled_education": "applicant.is_enrolled_formal_education",
    "occupation": "employment.occupation",
    "income_annual": "household.income_annual",
    "income_monthly": "household.income_monthly",
    "bpl": "household.bpl_status",
    "residence": "household.residence_type",
    "pucca_house": "household.has_pucca_house",
    "lpg": "household.has_lpg_connection",
    "family_size": "household.family_size",
    "epfo": "employment.is_epfo_member",
    "esic": "employment.is_esic_member",
    "nps": "employment.is_nps_subscriber",
    "income_tax": "employment.is_income_tax_payer",
    "govt_employee": "employment.is_government_employee",
    "aadhaar": "documents.aadhaar",
    "bank_account": "documents.bank_account",
    "ration_card": "documents.ration_card",
    "caste_certificate": "documents.caste_certificate",
    "disability_certificate": "documents.disability_certificate",
    "vending_certificate": "documents.vending_certificate",
    "ssy_account": "documents.has_ssy_account",
    "cultivable_land": "assets.cultivable_land",
    "land_owner": "assets.land_owner",
    "crop_type": "assets.crop_type",
    "state": "location.state",
    "district": "location.district",
}

AMBIGUITY_TYPES = {
    1: "Vague Threshold",
    2: "Overlapping Categories",
    3: "Proxy Measure Conflict",
    4: "Discretionary Clauses",
    5: "Temporal Ambiguity",
    6: "Tenure Ambiguity",
    7: "Critical Data Gap",
    8: "Geographic Scope Conflict",
    9: "Account Type Ambiguity",
    10: "State Variation",
    11: "Classification Overlap",
    12: "Aggregation Ambiguity",
    13: "Compound Qualifier",
    14: "Self-Certification Risk",
    15: "Currency/Unit Mismatch",
    16: "Residency Duration",
    17: "Exclusion List Incomplete",
    18: "Benefit Cap Ambiguity",
    19: "Family vs Individual",
    20: "Double Negation",
    21: "Conditional Prerequisite",
    22: "Retroactive Eligibility",
    23: "Multiple Scheme Interaction",
    24: "Numeric Range Open-ended",
    25: "Missing Operator",
    26: "Gender Ambiguity",
    27: "Document Not Defined",
    28: "Age Boundary Edge Case",
    29: "Category Not Standardized",
    30: "Benefit Type Ambiguity",
}


@dataclass
class AmbiguityFlag:
    ambiguity_id: str
    scheme_id: str
    rule_id: str
    ambiguity_type_code: int
    ambiguity_type_name: str
    description: str
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    resolution_status: str = "OPEN"

    def to_dict(self):
        return asdict(self)


@dataclass
class Rule:
    Rule_ID: str
    Scheme_ID: str
    Rule_Type: str  # eligibility, disqualifying, prerequisite
    Condition_Type: str
    Field: str
    Operator: str
    Value: Optional[Any] = None
    Value_Min: Optional[Any] = None
    Value_Max: Optional[Any] = None
    Values: List[Any] = field(default_factory=list)
    Condition: str = ""
    Source_Quote: str = ""
    Source_URL: str = ""
    Confidence: float = 0.5
    Audit_Status: str = "PENDING"
    Display_Text: str = ""
    Version: str = "1.0.0-kaggle"
    Data_Source_Tier: int = 3
    Ambiguity_Flags: List[str] = field(default_factory=list)
    Notes: Optional[str] = None
    logic_group: Optional[str] = None
    logic_operator: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        if d["Ambiguity_Flags"] is None:
            d["Ambiguity_Flags"] = []
        return d


@dataclass
class Scheme:
    scheme_id: str
    scheme_name: str
    short_name: str
    status: str = "active"
    state_scope: str = "central"
    data_source_tier: int = 3
    version: str = "1.0.0-kaggle"
    parse_run_id: str = ""
    rules: List[Rule] = field(default_factory=list)
    review_queue: Dict[str, Any] = field(default_factory=lambda: {
        "flagged": False,
        "reason": None,
        "severity": None
    })

    def to_dict(self):
        return {
            "scheme_id": self.scheme_id,
            "scheme_name": self.scheme_name,
            "short_name": self.short_name,
            "status": self.status,
            "state_scope": self.state_scope,
            "data_source_tier": self.data_source_tier,
            "version": self.version,
            "parse_run_id": self.parse_run_id,
            "rules": [r.to_dict() for r in self.rules],
            "review_queue": self.review_queue
        }


# ==================== PARSING ENGINE ====================

class KaggleParsingEngine:
    def __init__(self):
        self.rule_counter = {}
        self.schemes_processed = 0
        self.ambiguities_found = []
        
    def normalize_state(self, level: str) -> str:
        """Map level to state code."""
        if not level or level.lower() == "central":
            return "central"
        level_lower = level.lower().strip()
        return STATE_CODES.get(level_lower, level.upper()[:2])

    def extract_numeric(self, text: str) -> Tuple[Optional[int], Optional[int]]:
        """Extract numeric values from text."""
        # Match patterns like "18", "between 18 and 40", "₹5 lakh"
        numbers = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', text)
        if not numbers:
            return None, None
        try:
            nums = [int(n.replace(',', '')) for n in numbers]
            return (min(nums), max(nums)) if len(nums) > 1 else (nums[0], None)
        except:
            return None, None

    def detect_ambiguities(self, text: str, slug: str, rule_id: str) -> List[AmbiguityFlag]:
        """Detect all 30 types of ambiguities."""
        flags = []
        text_lower = text.lower()

        # Type 1: Vague Threshold
        if re.search(r'\b(poor|needy|economically weak|backward|weaker)\b', text_lower):
            if not re.search(r'₹|\d+', text):
                flags.append(AmbiguityFlag(
                    ambiguity_id=f"AMB-{slug}-{len(flags)+1:03d}",
                    scheme_id=f"{slug}-KAGGLE",
                    rule_id=rule_id,
                    ambiguity_type_code=1,
                    ambiguity_type_name="Vague Threshold",
                    description="Condition uses vague terms without numeric quantification.",
                    severity="MEDIUM"
                ))

        # Type 4: Discretionary Clauses
        if re.search(r'\b(may be|discretion|subject to|at the discretion|subject to availability)\b', text_lower):
            flags.append(AmbiguityFlag(
                ambiguity_id=f"AMB-{slug}-{len(flags)+1:03d}",
                scheme_id=f"{slug}-KAGGLE",
                rule_id=rule_id,
                ambiguity_type_code=4,
                ambiguity_type_name="Discretionary Clauses",
                description="Rule contains discretionary language that may be applied variably.",
                severity="HIGH"
            ))

        # Type 5: Temporal Ambiguity
        if re.search(r'\b(before|after|since|for at least|for last)\b', text_lower):
            if re.search(r'\d+\s*(year|month|day|date)', text_lower, re.IGNORECASE):
                flags.append(AmbiguityFlag(
                    ambiguity_id=f"AMB-{slug}-{len(flags)+1:03d}",
                    scheme_id=f"{slug}-KAGGLE",
                    rule_id=rule_id,
                    ambiguity_type_code=5,
                    ambiguity_type_name="Temporal Ambiguity",
                    description="Temporal criteria present that are relative to cutoff dates.",
                    severity="MEDIUM"
                ))

        # Type 10: State Variation
        if re.search(r'\b(varies by state|as per state|state specific|state-level)\b', text_lower):
            flags.append(AmbiguityFlag(
                ambiguity_id=f"AMB-{slug}-{len(flags)+1:03d}",
                scheme_id=f"{slug}-KAGGLE",
                rule_id=rule_id,
                ambiguity_type_code=10,
                ambiguity_type_name="State Variation",
                description="Eligibility varies by state; cannot be uniformly applied.",
                severity="HIGH"
            ))

        # Type 14: Self-Certification Risk
        if re.search(r'\b(self.?certif|self.?declar|self.?attest|self.?report)\b', text_lower, re.IGNORECASE):
            flags.append(AmbiguityFlag(
                ambiguity_id=f"AMB-{slug}-{len(flags)+1:03d}",
                scheme_id=f"{slug}-KAGGLE",
                rule_id=rule_id,
                ambiguity_type_code=14,
                ambiguity_type_name="Self-Certification Risk",
                description="Eligibility relies on self-certification without stated verification.",
                severity="MEDIUM"
            ))

        # Type 17: Exclusion List Incomplete
        if re.search(r'\bsuch as\b', text_lower):
            flags.append(AmbiguityFlag(
                ambiguity_id=f"AMB-{slug}-{len(flags)+1:03d}",
                scheme_id=f"{slug}-KAGGLE",
                rule_id=rule_id,
                ambiguity_type_code=17,
                ambiguity_type_name="Exclusion List Incomplete",
                description="List uses 'such as' implying non-exhaustive enumeration.",
                severity="LOW"
            ))

        # Type 20: Double Negation
        if re.search(r'\b(not ineligible|no bar on|not excluded|not disqualified)\b', text_lower):
            flags.append(AmbiguityFlag(
                ambiguity_id=f"AMB-{slug}-{len(flags)+1:03d}",
                scheme_id=f"{slug}-KAGGLE",
                rule_id=rule_id,
                ambiguity_type_code=20,
                ambiguity_type_name="Double Negation",
                description="Double negation present which may confuse eligibility.",
                severity="MEDIUM"
            ))

        # Type 23: Multiple Scheme Interaction
        if re.search(r'\b(other scheme|already enrolled|existing beneficiary|concurrent|another scheme)\b', text_lower):
            flags.append(AmbiguityFlag(
                ambiguity_id=f"AMB-{slug}-{len(flags)+1:03d}",
                scheme_id=f"{slug}-KAGGLE",
                rule_id=rule_id,
                ambiguity_type_code=23,
                ambiguity_type_name="Multiple Scheme Interaction",
                description="Eligibility depends on status in other schemes.",
                severity="HIGH"
            ))

        # Type 28: Age Boundary Edge Case
        if re.search(r'\b(at least|above|below|between)\s*\d+\s*(year|age)', text_lower):
            flags.append(AmbiguityFlag(
                ambiguity_id=f"AMB-{slug}-{len(flags)+1:03d}",
                scheme_id=f"{slug}-KAGGLE",
                rule_id=rule_id,
                ambiguity_type_code=28,
                ambiguity_type_name="Age Boundary Edge Case",
                description="Age boundary present; inclusion/exclusion at boundary unclear.",
                severity="LOW"
            ))

        return flags

    def classify_rule_type(self, text: str, field: str) -> Tuple[str, List[AmbiguityFlag]]:
        """Classify rule as eligibility, disqualifying, or prerequisite."""
        text_lower = text.lower()
        flags = []

        # Disqualifying patterns
        disqualifying_patterns = [
            r'\bmust not\b',
            r'\bcannot\b',
            r'\bnot eligible if\b',
            r'\bexcluded if\b',
            r'\bno existing\b',
            r'\bnot covered\b',
            r'\bshould not\b',
            r'\bdisqualified if\b',
            r'\balready\s*(?:have|has|own|hold)',
        ]
        
        for pattern in disqualifying_patterns:
            if re.search(pattern, text_lower):
                return "disqualifying", flags

        # Prerequisite patterns
        prerequisite_patterns = [
            r'\b(?:required|compulsory|mandatory|must have|is mandatory)\b',
            r'\b(?:bank account|aadhaar|ration card|certificate)\s*(?:required|compulsory|mandatory)',
            r'\bmust.*(?:register|enroll|open|obtain)\b',
        ]
        
        for pattern in prerequisite_patterns:
            if re.search(pattern, text_lower):
                # But not if it's written as a standard condition
                if not re.search(r'\b(?:applicant|beneficiary)\s+(?:must\s+)?have\b', text_lower):
                    return "prerequisite", flags

        return "eligibility", flags

    def extract_canonical_field(self, text: str) -> str:
        """Map sentence text to canonical field namespace."""
        t = text.lower()
        # Age
        if re.search(r'\b(age|years?\s+old|aged\s|born\s|age\s+group|\d+\s*-\s*\d+\s*years?)\b', t):
            return "applicant.age"
        # Gender
        if re.search(r'\b(female|women|woman|girl|male|man|men|boy|transgender|gender)\b', t):
            return "applicant.gender"
        # Marital status (check before caste to avoid widow/SC overlap)
        if re.search(r'\b(widow|widower|widowed|married|unmarried|divorced|separated|single\s+woman|spouse|deserted)\b', t):
            return "applicant.marital_status"
        # Disability
        if re.search(r'\b(disab|handicap|differently.?abled|pwd|locomotor|blind|deaf|mute|physical.?challenge)\b', t):
            return "applicant.disability_status"
        # Caste
        if re.search(r'\b(sc|st|obc|general\s+category|backward\s+class|scheduled\s+caste|scheduled\s+tribe|minority|ews|economically\s+weaker)\b', t):
            return "applicant.caste_category"
        # Education
        if re.search(r'\b(education|qualification|class\s+\d|grade\s+\d|school|graduate|literate|illiterate|diploma|degree|10th|12th|matric|ssc|hsc|inter|passed)\b', t):
            return "applicant.education_level"
        # Income tax payer (employment attribute — must precede generic income check)
        if re.search(r'\b(income\s+tax|income-tax|itr|tax\s+payer|taxpayer)\b', t):
            return "employment.is_income_tax_payer"
        # Income / monetary thresholds
        if re.search(r'\b(income|earning|salary|wage|annual\s+income|monthly\s+income|per\s+annum|per\s+month|₹|inr|lakh|crore|rupee|rs\.?)\b', t):
            return "household.income_annual"
        # BPL
        if re.search(r'\b(bpl|below\s+poverty\s+line|apl|above\s+poverty)\b', t):
            return "household.bpl_status"
        # Occupation / employment
        if re.search(r'\b(farmer|agricult|worker|employee|self.?employ|profession|labor|labour|artisan|fisherm|weaver|craftsmen|business|trade|vendor|driver|mason|cobbler|scavenger|unorganis|informal|gig)\b', t):
            return "employment.occupation"
        # Aadhaar
        if re.search(r'\b(aadhaar|uid\b|biometric\s+id)\b', t, re.IGNORECASE):
            return "documents.aadhaar"
        # Bank account
        if re.search(r'\b(bank\s+account|jan\s+dhan|savings\s+account|pmjdy)\b', t):
            return "documents.bank_account"
        # Ration card
        if re.search(r'\b(ration\s+card|pds|public\s+distribution|food\s+security)\b', t):
            return "documents.ration_card"
        # Land / agricultural assets
        if re.search(r'\b(land|acre|hectare|cultivab|farm\s+land|landowner|agricultural\s+land)\b', t):
            return "assets.cultivable_land"
        # Residency / domicile
        if re.search(r'\b(resident|domicile|residing|native\s+of|citizen\s+of|permanent\s+resident|staying\s+in|belonging\s+to\s+(?:the\s+)?state)\b', t):
            return "location.state"
        # State / district (location context)
        if re.search(r'\b(state\s+of|district\s+of|union\s+territory\s+of|taluk|block\s+of)\b', t):
            return "location.state"
        # Family / household size
        if re.search(r'\b(family\s+size|household\s+member|family\s+member|number\s+of\s+member)\b', t):
            return "household.family_size"
        return "eligibility.other"

    def map_condition_type(self, text: str, field: str) -> str:
        """Infer Condition_Type from canonical field name."""
        if "age" in field:
            return "age_range"
        elif "employment" in field:
            # Specific employment sub-types
            if "income_tax" in field:
                return "employment:income_tax_status"
            elif "govt_employee" in field:
                return "employment:govt_employee_status"
            elif "epfo" in field or "esic" in field or "nps" in field:
                return "employment:social_security_status"
            return "occupation"
        elif "income" in field:
            return "income_ceiling"
        elif "gender" in field:
            return "gender"
        elif "caste" in field:
            return "caste_category"
        elif "occupation" in field:
            return "occupation"
        elif "residence" in field or ("location" in field and "state" in field):
            return "domicile"
        elif "bpl" in field or "poverty" in field:
            return "poverty_status"
        elif "documents" in field:
            doc_part = field.split(".")[-1] if "." in field else field
            return f"document:{doc_part}"
        elif "disability" in field:
            return "disability"
        elif "marital" in field:
            return "marital_status"
        elif "education" in field:
            return "education_level"
        elif "land" in field or "assets" in field:
            return "land_ownership"
        elif "family" in field:
            return "family_size"
        else:
            return "other"

    def extract_in_values(self, text: str, field: str) -> List[str]:
        """Extract enumerated values for IN operator."""
        t = text.lower()
        # Caste categories
        if "caste" in field:
            found = []
            for cat in ["SC", "ST", "OBC", "EWS", "General", "GEN", "BC", "MBC", "NT", "SBC", "VJ"]:
                if cat.lower() in t or cat in text:
                    found.append(cat)
            if found:
                return found
        # Gender
        if "gender" in field:
            found = []
            if re.search(r'\bfemale|women|woman\b', t): found.append("female")
            if re.search(r'\bmale|men|man\b', t): found.append("male")
            if re.search(r'\btransgender\b', t): found.append("transgender")
            if found:
                return found
        # Occupation
        if "occupation" in field:
            occupations = re.findall(r'(?:farmer|worker|artisan|weaver|fisherm\w*|driver|mason|carpenter|cobbler|potter|blacksmith)', t)
            if occupations:
                return list(set(occupations))
        # Education levels
        if "education" in field:
            levels = []
            for lvl in ["10th", "12th", "graduate", "post-graduate", "diploma", "illiterate", "literate"]:
                if lvl in t:
                    levels.append(lvl)
            if levels:
                return levels
        # Marital status
        if "marital" in field:
            statuses = []
            for s in ["widow", "divorced", "separated", "unmarried", "married", "deserted"]:
                if s in t:
                    statuses.append(s)
            if statuses:
                return statuses
        return []

    def _parse_indian_currency(self, text: str) -> Optional[int]:
        """Extract integer rupee amount from Indian-formatted currency strings.

        Handles: Rs. 2,50,000 / ₹2.5 lakh / 3 lakh / 1.5 crore / 300000
        """
        t = text.lower()
        # Lakh: "2 lakh", "2.5 lakh", "Rs. 2,50,000"
        m = re.search(r'(?:₹|rs\.?\s*)(\d+(?:[.,]\d+)*)\s*lakh', t)
        if m:
            return int(float(m.group(1).replace(',', '')) * 100000)
        m = re.search(r'(\d+(?:\.\d+)?)\s*lakh', t)
        if m:
            return int(float(m.group(1)) * 100000)
        # Crore
        m = re.search(r'(\d+(?:\.\d+)?)\s*crore', t)
        if m:
            return int(float(m.group(1)) * 10000000)
        # Plain Indian formatted number after ₹/Rs. e.g. "Rs. 2,50,000"
        m = re.search(r'(?:₹|rs\.?\s*)(\d[\d,]*)', t)
        if m:
            return int(m.group(1).replace(',', ''))
        return None

    def extract_operator(self, text: str) -> Tuple[str, Optional[Any], Optional[Any], List[Any]]:
        """Extract operator and values from text."""
        t = text.lower()

        # Income-aware LTE: "not exceed Rs. X", "income below Rs. X", "up to Rs. X lakh"
        if re.search(r'\b(?:not\s+exceed|should\s+not\s+exceed|must\s+not\s+exceed|below|up\s+to|upto|maximum|at\s+most|not\s+more\s+than)', t):
            amt = self._parse_indian_currency(text)
            if amt is not None:
                return "LTE", amt, None, []

        # Income-aware GTE: "at least Rs. X", "minimum Rs. X", "above Rs. X"
        if re.search(r'\b(?:at\s+least|minimum|above|not\s+less\s+than)\b', t):
            amt = self._parse_indian_currency(text)
            if amt is not None:
                return "GTE", amt, None, []

        # BETWEEN: "between X and Y"
        m = re.search(r'\bbetween\s*(\d+)\s*and\s*(\d+)\b', t)
        if m:
            return "BETWEEN", int(m.group(1)), int(m.group(2)), []

        # BETWEEN: "X to Y years" / "X-Y years" / "age group X-Y" / "aged X-Y"
        m = re.search(r'(\d+)\s*(?:to|[-–])\s*(\d+)\s*(?:years?|yrs?|age)', t)
        if m:
            return "BETWEEN", int(m.group(1)), int(m.group(2)), []

        # BETWEEN: "from X to Y"
        m = re.search(r'\bfrom\s*(\d+)\s*to\s*(\d+)\b', t)
        if m:
            return "BETWEEN", int(m.group(1)), int(m.group(2)), []

        # GTE: "at least X", "minimum X", "X or above", "X or older", "X years and above"
        m = re.search(r'\b(?:at\s+least|minimum|not\s+less\s+than)\s*(\d+)', t)
        if m:
            return "GTE", int(m.group(1)), None, []
        m = re.search(r'(\d+)\s*(?:years?|yrs?)?\s*(?:or\s+)?(?:above|older|and\s+above|\+)', t)
        if m:
            return "GTE", int(m.group(1)), None, []

        # LTE: "at most", "up to", "not exceed", "X or below", "not more than"
        m = re.search(r'\b(?:at\s+most|up\s+to|upto|maximum|not\s+(?:more|exceed)|no\s+more\s+than|not\s+exceeding)\s*(\d+)', t)
        if m:
            return "LTE", int(m.group(1)), None, []
        m = re.search(r'(\d+)\s*(?:years?|yrs?)?\s*(?:or\s+)?(?:below|younger|and\s+below|and\s+under)', t)
        if m:
            return "LTE", int(m.group(1)), None, []

        # GT: "more than X", "greater than X", "above X" (no 'or')
        m = re.search(r'\b(?:more\s+than|greater\s+than|above)\s*(\d+)', t)
        if m:
            return "GT", int(m.group(1)), None, []

        # LT: "less than X", "below X" (strict)
        m = re.search(r'\b(?:less\s+than|below|under)\s*(\d+)', t)
        if m:
            return "LT", int(m.group(1)), None, []

        # IN: caste / category list patterns
        if re.search(r'\b(?:sc|st|obc|ews)\b.*(?:\/|or|and).*\b(?:sc|st|obc|ews|general)\b', t):
            return "IN", None, None, []
        if re.search(r'\b(?:one\s+of|belonging\s+to|either|category|categories)\b', t):
            return "IN", None, None, []
        if re.search(r'\b(male|female)\b.*\b(female|male|transgender)\b', t):
            return "IN", None, None, []

        # EQ/NEQ for boolean or exact match
        if re.search(r'\b(?:must\s+be|should\s+be|shall\s+be|is\s+a|is\s+an|are\s+a)\b', t):
            return "EQ", None, None, []

        return "EQ", None, None, []

    def score_confidence(self, text: str, operator: str, value: Any) -> float:
        """Score extraction confidence."""
        # Exact numeric with clear operator
        if operator in ["BETWEEN", "GTE", "LTE", "GT", "LT"] and value is not None:
            if re.search(r'(?:₹|INR|lakh|crore|rupee)', text, re.IGNORECASE):
                return 0.92
            return 0.95
        
        # Clear intent but slight paraphrase
        if "must" in text.lower() or "should" in text.lower():
            return 0.85
        
        # Reasonable but indirect
        if "may" in text.lower() or "can" in text.lower():
            return 0.72
        
        # Multiple interpretations
        if "or" in text.lower() and "and" in text.lower():
            return 0.65
        
        # Vague or ambiguous
        if any(w in text.lower() for w in ["some", "any", "may vary", "subject"]):
            return 0.55
        
        return 0.70

    def build_condition_text(self, field: str, operator: str, value: Any,
                              val_min: Any, val_max: Any, source_text: str) -> str:
        """Build a human-readable Condition description."""
        field_short = field.split('.')[-1].replace('_', ' ') if '.' in field else field.replace('_', ' ')
        if operator == "BETWEEN" and val_min is not None and val_max is not None:
            return f"{field_short} between {val_min} and {val_max}"
        elif operator == "GTE" and value is not None:
            return f"{field_short} \u2265 {value}"
        elif operator == "LTE" and value is not None:
            return f"{field_short} \u2264 {value}"
        elif operator == "GT" and value is not None:
            return f"{field_short} > {value}"
        elif operator == "LT" and value is not None:
            return f"{field_short} < {value}"
        elif operator == "IN":
            return f"{field_short} in eligible categories"
        elif operator == "EQ" and value is not None:
            return f"{field_short} = {value}"
        # Fall back to truncated source text
        return source_text[:120] if len(source_text) <= 120 else source_text[:117] + "..."

    def extract_rules(self, scheme_id: str, slug: str, eligibility_text: str) -> Tuple[List[Rule], List[AmbiguityFlag]]:
        """Extract all rules from eligibility text."""
        rules = []
        all_ambiguities = []

        if not eligibility_text or not eligibility_text.strip():
            rule = Rule(
                Rule_ID=f"{slug}-K-R001",
                Scheme_ID=f"{slug}-KAGGLE",
                Rule_Type="eligibility",
                Condition_Type="other",
                Field="eligibility.other",
                Operator="EQ",
                Condition="No eligibility criteria extracted",
                Source_Quote="",
                Source_URL=f"kaggle://indian-government-schemes/{slug}",
                Confidence=0.0,
                Display_Text="Empty eligibility text",
                Notes="Empty eligibility text"
            )
            rules.append(rule)
            return rules, all_ambiguities

        # Split into sentences
        sentences = re.split(r'[.!?]\s+', eligibility_text)
        rule_counter = 1

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:  # Skip very short fragments
                continue

            # 1. Classify rule type
            rule_type, temp_ambigs = self.classify_rule_type(sentence, "general")
            all_ambiguities.extend(temp_ambigs)

            # 2. Detect ambiguities
            ambigs = self.detect_ambiguities(sentence, slug, f"{slug}-K-R{rule_counter:03d}")
            all_ambiguities.extend(ambigs)

            # 3. Extract canonical field from sentence text
            canonical_field = self.extract_canonical_field(sentence)
            condition_type = self.map_condition_type(sentence, canonical_field)

            # 4. Extract operator and numeric values
            operator, val, val_max, vals = self.extract_operator(sentence)

            # 5. For BETWEEN: Value should be None; min/max carry the range
            if operator == "BETWEEN":
                rule_value = None
                rule_value_min = val      # val = lower bound from extract_operator
                rule_value_max = val_max  # val_max = upper bound
            else:
                rule_value = val
                rule_value_min = None
                rule_value_max = None

            # 6. For IN: extract enumerated values from text
            if operator == "IN":
                vals = self.extract_in_values(sentence, canonical_field)

            # 7. Compute confidence
            primary_val_for_confidence = val if operator != "BETWEEN" else val
            confidence = self.score_confidence(sentence, operator, primary_val_for_confidence)

            # 8. Build human-readable Condition text
            condition_text = self.build_condition_text(
                canonical_field, operator, rule_value, rule_value_min, rule_value_max, sentence
            )

            rule = Rule(
                Rule_ID=f"{slug}-K-R{rule_counter:03d}",
                Scheme_ID=f"{slug}-KAGGLE",
                Rule_Type=rule_type,
                Condition_Type=condition_type,
                Field=canonical_field,
                Operator=operator,
                Value=rule_value,
                Value_Min=rule_value_min,
                Value_Max=rule_value_max,
                Values=vals,
                Condition=condition_text,
                Source_Quote=sentence[:200],
                Source_URL=f"kaggle://indian-government-schemes/{slug}",
                Confidence=confidence,
                Display_Text=sentence[:100],
                Ambiguity_Flags=[f"AMB-{slug}-{i:03d}" for i, _ in enumerate(ambigs)]
            )
            rules.append(rule)
            rule_counter += 1

        return rules, all_ambiguities

    def should_flag_review(self, rules: List[Rule], ambiguities: List[AmbiguityFlag]) -> Tuple[bool, Optional[str], Optional[str]]:
        """Determine if scheme should be flagged for review."""
        # HIGH/CRITICAL ambiguities
        for amb in ambiguities:
            if amb.severity in ["HIGH", "CRITICAL"]:
                return True, f"Ambiguity: {amb.ambiguity_type_name}", amb.severity

        # Low confidence
        for rule in rules:
            if rule.Confidence < 0.65:
                return True, f"Low confidence ({rule.Confidence:.2f})", "MEDIUM"

        # Multiple ambiguities
        if len(ambiguities) > 3:
            return True, f"Multiple ambiguities detected ({len(ambiguities)})", "MEDIUM"

        # Discretionary language
        if any("discretion" in r.Source_Quote.lower() or "subject to" in r.Source_Quote.lower() 
               for r in rules):
            return True, "Contains discretionary language", "MEDIUM"

        return False, None, None

    def parse_scheme(self, row: Dict[str, str], parse_run_id: str) -> Scheme:
        """Parse a single scheme row."""
        scheme_name = row.get("scheme_name", "")
        slug = row.get("slug", "").lower()
        eligibility = row.get("eligibility", "")
        level = row.get("level", "Central")
        
        # Normalize short name
        short_name = slug.upper().replace("-", "")[:10]

        scheme = Scheme(
            scheme_id=f"{slug.upper()}-KAGGLE",
            scheme_name=scheme_name,
            short_name=short_name,
            state_scope=self.normalize_state(level),
            parse_run_id=parse_run_id
        )

        # Extract rules
        rules, ambiguities = self.extract_rules(scheme.scheme_id, slug, eligibility)
        scheme.rules = rules

        # Determine review flag
        flagged, reason, severity = self.should_flag_review(rules, ambiguities)
        scheme.review_queue = {
            "flagged": flagged,
            "reason": reason,
            "severity": severity
        }

        self.schemes_processed += 1
        if ambiguities:
            self.ambiguities_found.extend(ambiguities)

        return scheme

    def process_batch(self, csv_path: str, batch_size: int = 50, start_row: int = 0, 
                     end_row: Optional[int] = None) -> List[Scheme]:
        """Process a batch of schemes from CSV."""
        schemes = []
        run_date = datetime.now().strftime("%Y%m%d")
        batch_num = (start_row // batch_size) + 1
        parse_run_id = f"RUN-KAGGLE-{run_date}-{batch_num:03d}"

        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i < start_row:
                    continue
                if end_row and i >= end_row:
                    break
                if i % batch_size == 0 and i > 0:
                    logger.info(f"Processed {i} schemes...")

                scheme = self.parse_scheme(row, parse_run_id)
                schemes.append(scheme)

                if len(schemes) >= batch_size:
                    break

        return schemes

    def save_batch(self, schemes: List[Scheme], output_path: str):
        """Save batch of schemes to JSON."""
        output = [s.to_dict() for s in schemes]
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(schemes)} schemes to {output_path}")

    def process_all_batches(self, csv_path: str, output_dir: str, batch_size: int = 50):
        """Process all schemes in batches."""
        import os
        os.makedirs(output_dir, exist_ok=True)

        # Count total rows
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            total_rows = sum(1 for _ in f) - 1  # Subtract header

        run_date = datetime.now().strftime("%Y%m%d")
        batch_num = 1

        for start_row in range(0, total_rows, batch_size):
            end_row = min(start_row + batch_size, total_rows)
            logger.info(f"Processing batch {batch_num} (rows {start_row+1}-{end_row})...")

            schemes = self.process_batch(csv_path, batch_size, start_row, end_row)
            output_path = os.path.join(output_dir, f"kaggle_schemes_batch_{batch_num:03d}.json")
            self.save_batch(schemes, output_path)

            batch_num += 1

        logger.info(f"Processing complete. Total schemes: {self.schemes_processed}")
        logger.info(f"Total ambiguities found: {len(self.ambiguities_found)}")


# ==================== MAIN ====================

if __name__ == "__main__":
    engine = KaggleParsingEngine()
    csv_path = "/Users/dhruv/Downloads/projects/cbc/updated_data.csv"
    output_dir = "/Users/dhruv/Downloads/projects/cbc/parsed_schemes"

    engine.process_all_batches(csv_path, output_dir, batch_size=50)
