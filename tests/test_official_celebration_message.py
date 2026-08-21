from bot.services.official_quiz import OfficialQuizService


def test_gsi_participant_congratulations_message_is_bold() -> None:
    text = OfficialQuizService._participant_congratulations_text("gsi")
    assert text == (
        "<b>🏆 GSI QUIZ में भाग लेने वाले सभी प्रतिभागियों को हार्दिक बधाई! 🎉</b>\n"
        "<b>🌟 सीखते रहिए • प्रयास करते रहिए • आगे बढ़ते रहिए</b>"
    )


def test_star_participant_congratulations_message_is_dynamic() -> None:
    text = OfficialQuizService._participant_congratulations_text("star")
    assert "<b>🏆 STAR ⭐ QUIZ में भाग लेने वाले सभी प्रतिभागियों को हार्दिक बधाई! 🎉</b>" in text
    assert "<b>🌟 सीखते रहिए • प्रयास करते रहिए • आगे बढ़ते रहिए</b>" in text
