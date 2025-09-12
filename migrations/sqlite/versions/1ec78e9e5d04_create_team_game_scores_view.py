"""create_team_game_scores_view

Revision ID: 1ec78e9e5d04
Revises: e6450d258c71
Create Date: 2025-06-03 22:24:11.838558

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1ec78e9e5d04'
down_revision: Union[str, None] = 'e6450d258c71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Creating a view to aggregate game scores for each team
    op.execute("""
    CREATE VIEW team_game_scores AS
    SELECT
        games.game_id,
        games.game_date,
        teams.team_id,
        teams.team_name,
        vybor.points AS vybor_points,
        chisla.total_sum AS chisla_points,
        pref.total_sum AS pref_points,
        pairs.points AS pairs_points,
        razobl.total_sum AS razobl_points,
        auction.total_sum AS auction_points,
        mot.total_sum AS mot_points,
        (
            COALESCE(vybor.points, 0) +
            COALESCE(chisla.total_sum, 0) +
            COALESCE(pref.total_sum, 0) +
            COALESCE(pairs.points, 0) +
            COALESCE(razobl.total_sum, 0) +
            COALESCE(auction.total_sum, 0) +
            COALESCE(mot.total_sum, 0)
        ) AS total_points
    FROM games
    JOIN game_teams ON games.game_id = game_teams.game_id
    JOIN teams ON game_teams.team_id = teams.team_id
    LEFT JOIN vybor ON (games.game_id = vybor.game_id AND teams.team_id = vybor.team_id)
    LEFT JOIN chisla ON (games.game_id = chisla.game_id AND teams.team_id = chisla.team_id)
    LEFT JOIN pref ON (games.game_id = pref.game_id AND teams.team_id = pref.team_id)
    LEFT JOIN pairs ON (games.game_id = pairs.game_id AND teams.team_id = pairs.team_id)
    LEFT JOIN razobl ON (games.game_id = razobl.game_id AND teams.team_id = razobl.team_id)
    LEFT JOIN auction ON (games.game_id = auction.game_id AND teams.team_id = auction.team_id)
    LEFT JOIN mot ON (games.game_id = mot.game_id AND teams.team_id = mot.team_id)
    """)

def downgrade():
    # Removing the view if it exists
    op.execute("DROP VIEW IF EXISTS team_game_scores")
