"""Step E4 party gold set: writes the synthetic documents and every gold label file. No model, no product code.

Three sources (README.md):

- ``fixture``: the five professional-brief fixtures; gold parties copied from their ``*.expected.json`` files.
- ``synthetic``: ten SYNTHETIC documents defined below. Each document is built from a list of ``Party`` and
  ``NonParty`` records and text templates that refer to them, so the ground truth is fixed **by construction**: the
  gold parties are exactly the ``Party`` records, and every name in the text comes from a record.
- ``public``: five trimmed public judgment excerpts (``build_public_excerpts.py``); their label files are written
  here **empty** (``label_status: "unlabelled"``) for a teammate to fill (LABELLING_GUIDE.md). Never overwritten once
  a teammate has labelled them.

    .venv/bin/python experiments/inlegalbert/party_gold/generate_gold.py

Re-running reproduces the committed files byte for byte (``--check`` verifies that without writing).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIXTURE_DIR = REPO / "backend/scripts/tests/fixtures/briefs"
FIXTURES = {"judgment": "judgment", "fir": "FIR", "chargesheet": "chargesheet", "petition": "petition", "unknown": "unknown"}
PUBLIC_IDS = ("p01_gujarat_hc_2021", "p02_andhra_hc_2023", "p03_punjab_hc_2023", "p04_supreme_court_2022", "p05_allahabad_hc_2019")
ROLES = ("appellant", "respondent", "petitioner", "applicant", "accused", "complainant", "informant")
BANNER = "SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD."
BANNER_FULL = (f"{BANNER} All names, places and numbers below are fictional and were invented for software testing. "
               "Any resemblance to real persons or organisations is coincidental.")
PAGE_BREAK = "\\f"


@dataclass(frozen=True)
class Party:
    name: str
    role: str
    alternative_roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class NonParty:
    name: str
    kind: str  # witness, investigating_officer, judge, victim, representative, relative, other


@dataclass
class SyntheticDoc:
    doc_id: str
    document_type: str
    parties: dict[str, Party]
    non_parties: dict[str, NonParty]
    pages: list[str]
    covers: list[str] = field(default_factory=list)

    def text(self) -> str:
        names = {**{k: v.name for k, v in self.parties.items()}, **{k: v.name for k, v in self.non_parties.items()}}
        body = f"\n{PAGE_BREAK}\n".join(page.strip("\n") for page in self.pages).format(**names)
        return f"{BANNER_FULL}\n\n{body}\n\n{BANNER}\n"


# ---------------------------------------------------------------------------
# The ten synthetic documents. Names and places are invented. Role cues vary on purpose: labelled lines
# ("Complainant: X"), cause titles ("X ... Appellants / Versus / Y"), numbered lists, and prose.
# ---------------------------------------------------------------------------

SYNTHETIC: list[SyntheticDoc] = [
    SyntheticDoc(
        doc_id="s01_fir_multi_accused", document_type="FIR",
        covers=["three accused", "alias (@)", "witness and officer as non-parties"],
        parties={"c": Party("Lakshmi Varadkar", "complainant", ("informant",)),
                 "a1": Party("Suresh Kotwalkar @ Sonu", "accused"),
                 "a2": Party("Imran Bhaldar", "accused"),
                 "a3": Party("Deepak Zambre", "accused")},
        non_parties={"w": NonParty("Mohan Pethkar", "witness"), "io": NonParty("Arvind Nagre", "investigating_officer")},
        pages=["""
FIRST INFORMATION REPORT
(Under Section 173 of the Bharatiya Nagarik Suraksha Sanhita, 2023)

1. District: Testgarh. Police Station: Mocknagar. FIR No. 0217/2024. Date: 11-06-2024.
2. Acts and Sections: Sections 115(2), 118(1) and 3(5) BNS.
3. Occurrence: 10-06-2024 at about 8:30 PM, near the weekly market, Mocknagar.
4. Name of complainant/informant: {c}, aged 45, vegetable vendor, Ward No. 4, Mocknagar.
5. Details of known accused:
   (i) {a1}, aged about 30, of Mocknagar;
   (ii) {a2}, aged about 27, of Station Road, Mocknagar;
   (iii) {a3}, aged about 32, of Mocknagar.
""", """
6. Contents of the complaint:
I, {c}, state that on 10-06-2024 at about 8:30 PM, while I was closing my stall, the accused {a1} came with his associates {a2} and {a3} and demanded money. When I refused, Sonu hit me with an iron rod and the other two pushed my son to the ground. {w}, who runs the tea stall nearby, saw the incident.
7. Action taken: the case was registered and the investigation was handed over to Sub-Inspector {io}.
"""]),
    SyntheticDoc(
        doc_id="s02_fir_org_complainant", document_type="FIR",
        covers=["organisation complainant", "informant acting for it", "company accused", "witness as non-party"],
        parties={"bank": Party("Samplepur Urban Co-operative Bank Ltd.", "complainant"),
                 "inf": Party("Nitin Deshmane", "informant"),
                 "a1": Party("Rakesh Bhosrekar", "accused"),
                 "co": Party("Orchid Fictional Traders Pvt. Ltd.", "accused"),
                 "a2": Party("Pallavi Bhosrekar", "accused")},
        non_parties={"w": NonParty("Anjali Kurhade", "witness")},
        pages=["""
FIRST INFORMATION REPORT
Police Station: Economic Offences Wing, Samplepur. FIR No. 0058/2024 dated 02.02.2024.
Sections: 318(4), 316(5) and 61(2) BNS.

Informant: {inf}, Branch Manager, Station Road branch.
Complainant: {bank}, acting through the informant.

Statement:
The informant states that {a1}, managing director of {co}, and his wife {a2}, a director of the same company, obtained a cash credit facility of Rs. 85,00,000 from the bank in 2022 by pledging stock that did not exist.
""", """
When the bank's inspection team, including clerk {w}, visited the godown on 15.01.2024, it was found empty. The accused company and both directors are alleged to have diverted the loan amount. The complainant bank requests action against all three accused.
"""]),
    SyntheticDoc(
        doc_id="s03_chargesheet_four_accused", document_type="chargesheet",
        covers=["four accused with numbers", "two aliases", "complainant also listed as witness", "doctor, panch and officer as non-parties"],
        parties={"c": Party("Prakash Hingmire", "complainant"),
                 "a1": Party("Manoj Gaikar @ Bunty", "accused"),
                 "a2": Party("Farhan Shaikhwadi", "accused"),
                 "a3": Party("Kavita Dongrekar", "accused"),
                 "a4": Party("Raju Tambolkar @ Raja", "accused")},
        non_parties={"w1": NonParty("Sneha Wavikar", "witness"), "dr": NonParty("Vinod Pathrekar", "witness"),
                     "panch": NonParty("Ganesh Ubale", "witness"), "io": NonParty("Shailesh Mokashi", "investigating_officer")},
        pages=["""
FINAL REPORT / CHARGE SHEET
(Under Section 193 of the Bharatiya Nagarik Suraksha Sanhita, 2023)
In the Court of the Chief Judicial Magistrate, Testgarh

Police Station: Riverside. FIR No. 0391/2024 dated 05.07.2024.
Offences: Sections 309(6), 3(5) and 61(2) BNS.
Name of the complainant: {c}, jeweller, Riverside Market.
Accused charge-sheeted:
A-1 {a1}, in custody;
A-2 {a2}, in custody;
A-3 {a3}, on bail;
A-4 {a4}, absconding.
""", """
Brief facts:
On 04.07.2024 at about 7 PM, A-1 and A-2 entered the complainant's shop armed with a knife, threatened the staff and took gold ornaments worth Rs. 6,20,000. A-3 had earlier visited the shop as a customer to observe it, and A-4 waited outside on a motorcycle.
Investigation: the accused Bunty and Farhan Shaikhwadi were arrested on 09.07.2024 and part of the ornaments was recovered at their instance in the presence of panch witness {panch}. The injured salesgirl {w1} identified A-1 and A-2 in a test identification parade. The medical certificate issued by Dr. {dr} records a cut injury on her hand.
List of witnesses: CW-1 {c}; CW-2 {w1}; CW-3 {dr}; CW-4 {panch}; CW-5 Inspector {io}, Investigating Officer.
"""]),
    SyntheticDoc(
        doc_id="s04_chargesheet_company_accused", document_type="chargesheet",
        covers=["company as accused", "director and absconder", "organisation complainant", "witness as non-party"],
        parties={"c": Party("Testgarh Agricultural Produce Market Committee", "complainant"),
                 "co": Party("Greenleaf Fictional Agro Pvt. Ltd.", "accused"),
                 "a1": Party("Harshad Malvankar", "accused"),
                 "a2": Party("Jitendra Sawlekar", "accused")},
        non_parties={"w": NonParty("Rupali Kadamwar", "witness")},
        pages=["""
CHARGE SHEET
(Under Section 173(2) Cr.P.C.)
In the Court of the Judicial Magistrate First Class, Testgarh
Police Station: Market Yard. FIR No. 0076/2023 dated 21.03.2023. Offences: Sections 420, 467, 468 and 471 IPC.

The complainant, {c}, through its secretary, reported that the accused company {co} submitted forged weighment slips to claim market-fee refunds between April 2021 and March 2022.

Investigation established that the accused Harshad Malvankar, director of the company, signed the refund claims, and that the accused {a2}, a former clerk of the Committee, prepared the forged slips. {a2} has absconded since 30.03.2023 and a proclamation has been issued against him.
""", """
The statement of {w}, accountant of the Committee, shows that the refunds were paid into the company's bank account.
The charge sheet is filed against Accused No. 1 {co}, Accused No. 2 {a1} and Accused No. 3 {a2} (absconding).
"""]),
    SyntheticDoc(
        doc_id="s05_petition_bail", document_type="petition",
        covers=["applicant who is also the accused", "State and complainant as respondents", "co-accused", "alias (@)"],
        parties={"app": Party("Vikas Rangnekar @ Vicky", "applicant", ("accused", "petitioner")),
                 "state": Party("State of Fictionaland", "respondent"),
                 "r2": Party("Shabana Mulani", "respondent", ("complainant",)),
                 "co": Party("Ajay Phadtare", "accused")},
        non_parties={},
        pages=["""
IN THE COURT OF THE SESSIONS JUDGE, SAMPLEPUR
CRIMINAL BAIL APPLICATION No. 1142 of 2024
(Application for regular bail under Section 483 of the Bharatiya Nagarik Suraksha Sanhita, 2023)

{app}, aged 24, resident of Samplepur ... Applicant
Versus
1. {state}, through Police Station Lakeview
2. {r2}, resident of Samplepur ... Respondents

The applicant above named most respectfully submits:
1. The applicant has been in custody since 14.08.2024 in FIR No. 0612/2024 registered at Police Station Lakeview on the report of respondent No. 2, the complainant, under Sections 309(4) and 3(5) BNS.
2. The co-accused {co}, against whom the same role is alleged, has already been released on bail by this Court on 02.09.2024.
""", """
3. The charge sheet has been filed on 30.09.2024 and the applicant's custody is no longer required for investigation.
PRAYER: The applicant prays that he be released on bail on such terms as this Court thinks fit.
"""]),
    SyntheticDoc(
        doc_id="s06_petition_quashing_multi", document_type="petition",
        covers=["two petitioners", "three respondents including a company", "complainant who is also a respondent"],
        parties={"p1": Party("Neha Saraswat", "petitioner"),
                 "p2": Party("Anil Saraswat", "petitioner"),
                 "state": Party("State of Fictionaland", "respondent"),
                 "fin": Party("Fictional Housing Finance Ltd.", "respondent"),
                 "r3": Party("Rohit Jadhavkar", "respondent", ("complainant",))},
        non_parties={},
        pages=["""
IN THE HIGH COURT OF FICTIONALAND AT SAMPLEPUR
CRIMINAL WRIT PETITION No. 2210 of 2024

1. {p1}
2. {p2}
both residents of Shanti Nagar, Samplepur ... Petitioners
Versus
1. {state}, through the Principal Secretary (Home)
2. {fin}, through its Authorised Officer
3. {r3} ... Respondents

PETITION UNDER ARTICLE 226 OF THE CONSTITUTION AND SECTION 528 BNSS
1. The petitioners, {p1} and her husband {p2}, purchased a flat financed by respondent No. 2 in 2019.
2. Respondent No. 3, the seller of the flat, lodged FIR No. 0333/2024 against the petitioners alleging that they forged a no-objection letter.
""", """
3. The petitioners submit that the letter was issued by respondent No. 2 itself and that the FIR is an attempt by {r3} to pressure them in a civil dispute about the sale price.
PRAYER: quash FIR No. 0333/2024 and direct respondent No. 2 to produce its original file.
"""]),
    SyntheticDoc(
        doc_id="s07_judgment_criminal_appeal", document_type="judgment",
        covers=["three appellants who were the accused", "one alias", "complainant who is a prosecution witness",
                "deceased, witnesses and judge as non-parties"],
        parties={"a1": Party("Gopal Ninave", "appellant", ("accused",)),
                 "a2": Party("Sitaram Ninave", "appellant", ("accused",)),
                 "a3": Party("Bharat Ninave @ Bhau", "appellant", ("accused",)),
                 "state": Party("State of Fictionaland", "respondent"),
                 "c": Party("Yamuna Ninave", "complainant", ("informant",))},
        non_parties={"dec": NonParty("Tukaram Ninave", "victim"), "pw2": NonParty("Dilip Kharat", "witness"),
                     "pw5": NonParty("Meena Joglekar", "witness"), "judge": NonParty("R. K. Fictionwala", "judge")},
        pages=["""
IN THE HIGH COURT OF FICTIONALAND AT SAMPLEPUR
CRIMINAL APPELLATE JURISDICTION
CRIMINAL APPEAL No. 512 of 2019

Gopal Ninave & Ors. .... Appellants
Versus
{state} .... Respondent

CORAM: HON'BLE MR. JUSTICE {judge}

JUDGMENT
1. The three appellants were convicted by the Sessions Judge, Testgarh on 18.04.2019 under Sections 304 Part II and 34 IPC for the death of {dec} and sentenced to seven years' rigorous imprisonment.
2. Appellant No. 1 {a1} and appellant No. 2 {a2} are brothers; appellant No. 3 {a3} is the son of appellant No. 1. The deceased was their cousin.
""", """
3. The prosecution case rests on the evidence of the complainant {c} (PW-1), the widow of the deceased, who lodged the FIR on 02.11.2017, and of the neighbour {pw2} (PW-2). The post-mortem was conducted by Dr. {pw5} (PW-5).
4. Learned counsel for the appellants submits that the incident arose out of a sudden quarrel over a boundary wall and that Bhau was not present.
5. On a careful reading of the evidence of PW-1 and PW-2, we find the presence of all three appellants proved. The appeal is dismissed.
"""]),
    SyntheticDoc(
        doc_id="s08_order_bail_cancellation", document_type="order",
        covers=["'Opposite Party' cause title", "respondent who is the accused", "applicant who is the complainant"],
        parties={"app": Party("Kamini Bhagwat", "applicant", ("complainant",)),
                 "state": Party("State of Fictionaland", "respondent"),
                 "r2": Party("Sameer Lonkar", "respondent", ("accused",))},
        non_parties={},
        pages=["""
HIGH COURT OF FICTIONALAND AT SAMPLEPUR
Court No. 12
Case :- CRIMINAL MISC. BAIL CANCELLATION APPLICATION No. 0871 of 2024
Applicant :- {app}
Opposite Party :- {state} and Another

ORDER
1. Heard learned counsel for the applicant and the learned Additional Government Advocate for the State.
2. This application seeks cancellation of the bail granted on 12.03.2024 to opposite party No. 2, namely, {r2}, who is the accused in Case Crime No. 0144 of 2024 under Sections 115(2) and 351(3) BNS, Police Station Old City.
3. The applicant, who is the complainant in the case, alleges that after his release the accused threatened her on 20.04.2024.
4. Issue notice to opposite party No. 2. List on 15.07.2024.
"""]),
    SyntheticDoc(
        doc_id="s09_order_cheque_complaint", document_type="order",
        covers=["firm as complainant acting through a partner (partner is not a party)", "single accused"],
        parties={"c": Party("Sunrise Fictional Traders", "complainant"),
                 "a": Party("Mahesh Tidke", "accused")},
        non_parties={"rep": NonParty("Ravindra Ostwal", "representative")},
        pages=["""
IN THE COURT OF THE JUDICIAL MAGISTRATE FIRST CLASS, SAMPLEPUR
Summary Criminal Case No. 0930 of 2024

ORDER BELOW EXHIBIT 1
The complainant, M/s {c}, a partnership firm acting through its partner {rep}, has filed this complaint under Section 138 of the Negotiable Instruments Act, 1881 alleging that cheque No. 004512 dated 05.05.2024 for Rs. 3,40,000 issued by {a} was dishonoured for insufficient funds.
The verification statement of the partner has been recorded. Prima facie, the ingredients of the offence are made out against the accused.
Issue process against the accused {a} under Section 138 of the Negotiable Instruments Act, returnable on 19.08.2024.
"""]),
    SyntheticDoc(
        doc_id="s10_unknown_legal_aid_minutes", document_type="unknown",
        covers=["no parties: named people without any legal role", "role words used generically"],
        parties={},
        non_parties={"plv": NonParty("Shobha Kale", "other"), "sec": NonParty("Dinesh Yewale", "other"),
                     "chair": NonParty("Varsha Inamdar", "other")},
        pages=["""
Minutes of the legal-awareness camp held at Gram Panchayat Hall, Khedgaon, Testgarh District
Date: 18-08-2024

Present: para-legal volunteer {plv}; panchayat secretary {sec}; about forty villagers.
Chaired by {chair}, member of the Taluka Legal Services Committee.

1. {plv} explained the right of every accused person to free legal aid and the rights of a complainant when the police refuse to register a report.
2. {sec} reported that three villagers had asked for help with land-record corrections; they were referred to the Taluka office.
3. {chair} announced that the next camp will cover domestic-violence protection orders.
"""]),
]


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def dumps(value: object) -> str:
    return json.dumps(value, indent=1, ensure_ascii=False) + "\n"


def synthetic_outputs() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for doc in SYNTHETIC:
        text = doc.text()
        for item in list(doc.parties.values()) + list(doc.non_parties.values()):
            assert item.name in text or item.name.split(" @ ")[0] in text, (doc.doc_id, item.name)
        for party in doc.parties.values():
            assert party.role in ROLES and all(r in ROLES for r in party.alternative_roles), (doc.doc_id, party)
        out[HERE / "synthetic" / f"{doc.doc_id}.txt"] = text
        out[HERE / "gold" / f"{doc.doc_id}.json"] = dumps({
            "doc_id": doc.doc_id, "source": "synthetic", "synthetic": True, "document_type": doc.document_type,
            "text_file": f"experiments/inlegalbert/party_gold/synthetic/{doc.doc_id}.txt",
            "label_status": "by_construction", "covers": doc.covers,
            "parties": [{"name": p.name, "role": p.role, "alternative_roles": list(p.alternative_roles)} for p in doc.parties.values()],
            "non_parties": [{"name": n.name, "kind": n.kind} for n in doc.non_parties.values()],
        })
    return out


def fixture_outputs() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for name, document_type in FIXTURES.items():
        expected = json.loads((FIXTURE_DIR / f"{name}.expected.json").read_text(encoding="utf-8"))
        assert expected["document_type"] == document_type
        out[HERE / "gold" / f"f_{name}.json"] = dumps({
            "doc_id": f"f_{name}", "source": "fixture", "synthetic": expected["synthetic"], "document_type": document_type,
            "text_file": f"backend/scripts/tests/fixtures/briefs/{expected['fixture']}",
            "label_status": "from_expected_file",
            "parties": [{"name": p["name"], "role": p["role"], "alternative_roles": []} for p in expected["parties"]],
            "non_parties": [],
        })
    return out


EMPTY_PUBLIC_LABELS = {"label_status": "unlabelled", "labeller": None, "labelled_on": None, "parties": [], "notes": ""}


def public_outputs() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for doc_id in PUBLIC_IDS:
        out[HERE / "public" / f"{doc_id}.labels.json"] = dumps({
            "doc_id": doc_id, "source": "public", "synthetic": False,
            "text_file": f"experiments/inlegalbert/party_gold/public/{doc_id}.txt", **EMPTY_PUBLIC_LABELS})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the committed files instead of writing")
    args = parser.parse_args()
    outputs = {**synthetic_outputs(), **fixture_outputs()}
    public = public_outputs()
    problems = 0
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                print("differs:", path.relative_to(REPO))
                problems += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for path, content in public.items():
        if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("label_status") != "unlabelled":
            continue  # a teammate's labels are never overwritten
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                print("differs:", path.relative_to(REPO))
                problems += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"{len(outputs)} gold/synthetic files, {len(public)} public label files", "OK" if not problems else f"{problems} differ")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
