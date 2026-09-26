"""
The example transcript served by ``/api/example``.

Kept in its own module because it is content rather than logic, and because it
has to be correct in a way that is easy to break: an example that no longer
exercises the shipped schemas still renders, still compiles, and demonstrates
nothing. That happened once -- the delivery scenario here was written for the
logistics patterns that measurement later replaced -- and the guard against it is
`test_the_shipped_example_exercises_a_measured_schema`.

Every shape below matches the corpora the schemas were derived from:

* tool results are the bare JSON payload filed under ``user``, which is what both
  APIGen-MT and the SWE-agent trajectories look like, and what the machine-output
  detector keys on;
* a declaration block is inline with the assistant's sentence, because in a *text*
  transcript a newline starts the next turn, which loses the role and makes the
  declaration look like something the user said.
"""

import json


def _reservation_payload() -> str:
    return json.dumps({
        "reservation_id": "0U4NPP",
        "user_id": "amelia_rossi_1651",
        "origin": "PHL",
        "destination": "DEN",
        "flight_type": "one_way",
        "flights": [{
            "flight_number": "HAT076",
            "date": "2024-05-22",
            "origin": "PHL",
            "destination": "DEN",
            "cabin": "economy",
            "price": 121.0,
            "bags_included": 1,
        }],
        "passengers": [{
            "name": "Amelia Rossi",
            "dob": "1990-04-11",
            "loyalty": "silver",
            "known_traveler": True,
        }],
        "payment_history": [{
            "payment_id": "credit_card_3244882",
            "amount": 121.0,
            "brand": "visa",
            "last_four": "3244",
        }],
        "insurance": "no",
        "status": "confirmed",
    })


def _fare_payload() -> str:
    return json.dumps({
        "results": [{
            "flight_number": "HAT076",
            "origin": "PHL",
            "destination": "DEN",
            "cabin": {
                "economy": {"seats": 3, "price": 121.0, "bags": 1},
                "business": {"seats": 2, "price": 488.0, "bags": 2},
            },
            "fare_difference_business": 367.0,
        }],
        "currency": "USD",
    })


#: The schema the example is written against. Measured, and the only one whose
#: patterns still describe something that exists.
SCHEMA = "travel"

#: One turn per line: `role: content`.
_READ_PATH = [
    "system: You are an airline support agent. The current time is 2024-05-15 15:00 EST.",
    "user: Hi, I need to change the cabin on reservation 0U4NPP. I am in economy class.",
    "user: " + _reservation_payload(),
    "assistant: Reservation 0U4NPP is booked in economy class, Philadelphia to Denver.",
    "user: Actually, could you upgrade me to business class for this trip?",
    "assistant: Certainly. Let me look up the fare difference.",
    "user: " + _fare_payload(),
    "assistant: I can upgrade you to business class for a difference of $367.00. Shall I proceed?",
    "user: Yes please, charge it to my credit card ending in 3244.",
    "assistant: Done. You are now booked in business class on flight HAT076.",
    "user: One more thing, can you confirm the flight number on that booking?",
    "assistant: You are on flight HAT076, Philadelphia to Denver, in business class.",
    "user: Great, thank you.",
]


def _say(text, **facts):
    """One assistant turn: prose, then an inline declaration block."""
    line = "assistant: " + text
    if not facts:
        return line
    return line + " <contextgc-state>" + json.dumps(
        {"assert": facts}, separators=(",", ":")
    ) + "</contextgc-state>"


#: Same conversation, but the agent states its own state. Three declarations and
#: a reversal, so the register is not just reporting a guess.
_WRITE_PATH = [
    "system: You are an airline support agent. The current time is 2024-05-15 15:00 EST.",
    "user: I need to change the cabin on reservation 0U4NPP. I am in economy class.",
    _say("Confirming reservation 0U4NPP.",
         active_reservation="0U4NPP", cabin_class="economy"),
    "user: Upgrade me to business class.",
    _say("Upgrading you now.", cabin_class="business"),
    "user: Actually, keep it in economy, I changed my mind.",
    _say("Reverting to economy.", cabin_class="economy"),
    "user: Thanks.",
]


def example() -> dict:
    """The payload behind ``GET /api/example``."""
    return {
        "transcript": "\n".join(_READ_PATH),
        "write_path_example": "\n".join(_WRITE_PATH),
        # Stated rather than guessed. The website used to infer the schema from
        # the text, which is one reason a stale example kept looking plausible.
        "entity_schema": SCHEMA,
        "schema_note": (
            "This example uses the `travel` schema, measured at 100% on 72 "
            "independent judgements across 52 real customer-service "
            "conversations. It changes cabin class mid-conversation, so the "
            "state register has something to supersede."
        ),
    }
