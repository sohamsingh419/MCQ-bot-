from bot.config import (
    NATIONAL_SUBJECTS,
    STATE_SPECIFIC_SUBJECTS,
    VALID_STATES,
    subjects_for_state,
    syllabus_topics_for,
)


def test_all_28_states_have_internal_category_topics() -> None:
    states = VALID_STATES - {"All India", "General"}
    assert len(states) == 28
    for state in states:
        assert len(syllabus_topics_for(state, "State History")) >= 5
        assert len(syllabus_topics_for(state, "State Art & Culture")) >= 20
        assert len(syllabus_topics_for(state, "State Geography")) >= 20
        assert len(syllabus_topics_for(state, "State Polity & Administration")) >= 15
        assert len(syllabus_topics_for(state, "State Current Affairs")) >= 15


def test_state_gk_and_india_gk_use_internal_union_without_new_ui_subjects() -> None:
    assert len(syllabus_topics_for("Rajasthan", "State GK")) >= 100
    assert len(syllabus_topics_for("All India", "General Knowledge")) >= 150
    assert set(STATE_SPECIFIC_SUBJECTS).issubset(set(subjects_for_state("Rajasthan")))
    assert set(NATIONAL_SUBJECTS).issubset(set(subjects_for_state("All India")))


def test_future_subjects_keep_legacy_topics_until_their_topic_files_are_added() -> None:
    science_topics = syllabus_topics_for("Rajasthan", "General Science")
    computer_topics = syllabus_topics_for("All India", "Computer")
    assert science_topics == ("Physics in daily life", "Motion, force and energy", "Matter and chemistry", "Acids, bases and salts", "Human biology", "Plants and animals", "Health and nutrition", "Environment and ecology", "Space and technology")
    assert computer_topics[0] == "Computer fundamentals"
