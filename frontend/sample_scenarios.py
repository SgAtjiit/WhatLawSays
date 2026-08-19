"""
Predefined sample legal scenarios for the WhatLawSays Streamlit UI.
Allows users to quickly test different edge cases, undetermined states,
and statutory reasoning outputs.
"""

SAMPLE_SCENARIOS = {
    "🏛️ Undetermined State (President's Residence Invitation)": {
        "title": "President's Residence Invitation (Undetermined Fact Test)",
        "scenario_text": "A person was going to enter the President's residence with an invitation to attend a party.",
        "jurisdiction": "India",
        "description": "Tests the system's ability to refrain from premature criminalization when facts do not establish an offense."
    },
    "💻 Cyber Financial Fraud & Electronic Evidence": {
        "title": "Cyber Financial Extortion & e-FIR Filing",
        "scenario_text": "An individual received fraudulent calls pretending to be a bank official, leading to an unauthorized wire transfer of Rs. 2,50,000 from their account. Digital transaction receipts and call recordings were saved.",
        "jurisdiction": "India",
        "description": "Tests BNS Cheating/Extortion classification along with BNSS Section 173 e-FIR procedures and BSS Section 63 electronic evidence certification."
    },
    "🛡️ Private Defence & Criminal Trespass Exoneration": {
        "title": "Self-Defence Against Violent Home Invasion",
        "scenario_text": "Late at night, an intruder armed with an iron rod forcibly broke open the door of a house and threatened the homeowner with severe bodily harm. The homeowner struck the intruder with a heavy stick in self-defence to protect their family.",
        "jurisdiction": "India",
        "description": "Tests BNS Criminal Trespass combined with Right of Private Defence (BNS Sections 38–44) exoneration evaluation."
    },
    "🚗 Negligent Driving & Hit-and-Run": {
        "title": "Over-speeding Vehicle Collision & Reporting Duty",
        "scenario_text": "A rashly driven vehicle collided with a pedestrian on a public road, causing grievous injuries. The driver immediately stopped, called emergency services (112), and reported the incident to the nearest police station.",
        "jurisdiction": "India",
        "description": "Tests BNS rash driving provisions (Sec 281/106) and compliance with citizen statutory reporting duties."
    }
}
