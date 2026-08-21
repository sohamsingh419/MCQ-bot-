import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from bot.config import get_settings
from bot.database.database import Database
from bot.database.models import OfficialQuiz, OfficialQuizParticipant, QuizHistory, UserAnswer


async def main() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        async with db.session_factory() as session:
            quizzes = list((await session.execute(select(OfficialQuiz).order_by(OfficialQuiz.id.desc()))).scalars())
            print(f"now_utc={datetime.now(timezone.utc).isoformat()}")
            print(f"database_url={settings.database_url}")
            for quiz in quizzes[:20]:
                participants = await session.execute(
                    select(OfficialQuizParticipant).where(OfficialQuizParticipant.quiz_id == quiz.id)
                )
                histories = await session.execute(
                    select(QuizHistory).where(QuizHistory.official_quiz_id == quiz.id)
                )
                answers = await session.execute(
                    select(UserAnswer).join(QuizHistory, QuizHistory.telegram_poll_id == UserAnswer.poll_id).where(
                        QuizHistory.official_quiz_id == quiz.id
                    )
                )
                print({
                    "id": quiz.id,
                    "slug": quiz.slug,
                    "type": quiz.quiz_type,
                    "status": quiz.status,
                    "title": quiz.title,
                    "question_count": quiz.question_count,
                    "current_question_number": quiz.current_question_number,
                    "current_poll_id": quiz.current_poll_id,
                    "round_ends_at": quiz.round_ends_at.isoformat() if quiz.round_ends_at else None,
                    "countdown_ends_at": quiz.countdown_ends_at.isoformat() if quiz.countdown_ends_at else None,
                    "starts_at": quiz.starts_at.isoformat() if quiz.starts_at else None,
                    "ends_at": quiz.ends_at.isoformat() if quiz.ends_at else None,
                    "halfway_sent": quiz.halfway_sent,
                    "participants": len(participants.scalars().all()),
                    "histories": len(histories.scalars().all()),
                    "answers": len(answers.scalars().all()),
                    "play_group_id": quiz.play_group_id,
                    "config_group_id": quiz.config_group_id,
                })
    finally:
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())
