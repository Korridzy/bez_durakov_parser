"""
Database service layer for accessing game data.
Uses existing db.py and db_helpers.py methods.
"""
import sys
import os
import traceback
from typing import List, Dict, Optional, Any
from datetime import date, datetime
import pandas as pd

# Add parent of mounted bd_shared directory to path so we can import bd_shared as package
sys.path.insert(0, '/')

from bd_shared.db import Database, Game, Team, TeamGameScore, normalize_team_name
from bd_shared.db_helpers import initialize_database
from sqlalchemy import func, text


class GameDataService:
    """Service for retrieving and processing game data."""

    def __init__(self):
        """Initialize database connection."""
        self.db = initialize_database()
        if not self.db:
            raise RuntimeError("Failed to initialize database")

    def get_all_games_summary(self) -> pd.DataFrame:
        """
        Get summary of all games.

        Returns:
            DataFrame with game summaries
        """
        session = self.db.Session()
        try:
            games = session.query(Game).all()
            data = [{
                'game_id': g.game_id,
                'game_date': g.game_date,
                'created_at': g.created_at
            } for g in games]
            return pd.DataFrame(data)
        finally:
            session.close()

    def get_game_by_id(self, game_id: int) -> Optional[Dict[str, Any]]:
        """
        Get full game data by ID.

        Args:
            game_id: Game ID

        Returns:
            Dictionary with game data or None
        """
        try:
            bd_game = self.db.get_game_data(game_id)
            return bd_game.get_data()
        except ValueError:
            return None
        except Exception as e:
            print(f"Error getting game {game_id}: {e}")
            print(traceback.format_exc())
            raise

    def get_games_by_date_range(self, start_date: date, end_date: Optional[date] = None) -> List[int]:
        """
        Get game IDs within a date range.

        Args:
            start_date: Start date
            end_date: End date (optional)

        Returns:
            List of game IDs
        """
        return self.db.get_game_ids_by_date(start_date, end_date)

    def get_team_game_scores(self, game_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get team game scores from the view.

        Args:
            game_id: Optional game ID to filter

        Returns:
            DataFrame with team scores
        """
        session = self.db.Session()
        try:
            query = session.query(TeamGameScore)
            if game_id is not None:
                query = query.filter(TeamGameScore.game_id == game_id)

            scores = query.all()
            data = [{
                'game_id': s.game_id,
                'team_id': s.team_id,
                'game_date': s.game_date,
                'team_name': s.team_name,
                'vybor_points': float(s.vybor_points) if s.vybor_points else 0,
                'chisla_points': float(s.chisla_points) if s.chisla_points else 0,
                'pref_points': float(s.pref_points) if s.pref_points else 0,
                'pairs_points': float(s.pairs_points) if s.pairs_points else 0,
                'razobl_points': float(s.razobl_points) if s.razobl_points else 0,
                'auction_points': float(s.auction_points) if s.auction_points else 0,
                'mot_points': float(s.mot_points) if s.mot_points else 0,
                'total_points': float(s.total_points) if s.total_points else 0
            } for s in scores]
            return pd.DataFrame(data)
        finally:
            session.close()

    def get_all_teams(self) -> pd.DataFrame:
        """
        Get all teams.

        Returns:
            DataFrame with all teams
        """
        session = self.db.Session()
        try:
            teams = session.query(Team).all()
            data = [{
                'team_id': t.team_id,
                'team_name': t.team_name
            } for t in teams]
            return pd.DataFrame(data)
        finally:
            session.close()

    def get_team_statistics(self, team_name: str) -> Dict[str, Any]:
        """
        Get statistics for a specific team.

        Args:
            team_name: Team name

        Returns:
            Dictionary with team statistics
        """
        session = self.db.Session()
        try:
            normalized_name = normalize_team_name(team_name)

            team = session.query(Team).filter_by(team_name=normalized_name).first()
            if not team:
                raise ValueError(f'Team {team_name} not found')

            scores = session.query(TeamGameScore).filter_by(team_id=team.team_id).all()

            if not scores:
                return {
                    'team_name': team.team_name,
                    'games_played': 0,
                    'statistics': {}
                }

            df = pd.DataFrame([{
                'game_date': s.game_date,
                'vybor_points': float(s.vybor_points) if s.vybor_points else 0,
                'chisla_points': float(s.chisla_points) if s.chisla_points else 0,
                'pref_points': float(s.pref_points) if s.pref_points else 0,
                'pairs_points': float(s.pairs_points) if s.pairs_points else 0,
                'razobl_points': float(s.razobl_points) if s.razobl_points else 0,
                'auction_points': float(s.auction_points) if s.auction_points else 0,
                'mot_points': float(s.mot_points) if s.mot_points else 0,
                'total_points': float(s.total_points) if s.total_points else 0
            } for s in scores])

            return {
                'team_name': team.team_name,
                'games_played': len(scores),
                'total_points_sum': df['total_points'].sum(),
                'total_points_avg': df['total_points'].mean(),
                'total_points_max': df['total_points'].max(),
                'total_points_min': df['total_points'].min(),
                'category_averages': {
                    'vybor': df['vybor_points'].mean(),
                    'chisla': df['chisla_points'].mean(),
                    'pref': df['pref_points'].mean(),
                    'pairs': df['pairs_points'].mean(),
                    'razobl': df['razobl_points'].mean(),
                    'auction': df['auction_points'].mean(),
                    'mot': df['mot_points'].mean()
                }
            }
        finally:
            session.close()

    def get_team_wins(self, team_name: str, year: Optional[int] = None) -> Dict[str, Any]:
        """
        Get games won by a specific team.

        A win is defined as the team having total_points equal to the
        maximum total_points for that game (ties included).

        Uses get_team_game_scores() data and pandas operations only —
        no additional DB-layer queries.

        Args:
            team_name: Team name (will be normalized)
            year: Optional year to filter games (e.g. 2025)

        Returns:
            Dictionary with team wins data:
            - team_name: normalized team name
            - year: year filter applied (or None)
            - wins_count: number of games won
            - games_played: number of games in the filtered set
            - wins: list of dicts with game details for each win
        """
        normalized_name = normalize_team_name(team_name)

        all_scores = self.get_team_game_scores()
        if all_scores.empty:
            return {
                'team_name': normalized_name,
                'year': year,
                'wins_count': 0,
                'games_played': 0,
                'wins': []
            }

        # Normalize all team names in the dataframe for comparison
        all_scores['team_name_normalized'] = all_scores['team_name'].apply(normalize_team_name)

        # Check if team exists in the data at all
        team_mask = all_scores['team_name_normalized'] == normalized_name
        if not team_mask.any():
            return {
                'team_name': normalized_name,
                'year': year,
                'wins_count': 0,
                'games_played': 0,
                'wins': []
            }

        # Apply year filter if specified
        if year is not None:
            all_scores['game_date'] = pd.to_datetime(all_scores['game_date'])
            all_scores = all_scores[all_scores['game_date'].dt.year == year]
            if all_scores.empty:
                return {
                    'team_name': normalized_name,
                    'year': year,
                    'wins_count': 0,
                    'games_played': 0,
                    'wins': []
                }
            # Recompute team mask after year filter
            team_mask = all_scores['team_name_normalized'] == normalized_name

        # Find the team's games in the filtered set
        team_game_ids = all_scores.loc[team_mask, 'game_id'].unique()
        games_played = len(team_game_ids)

        if games_played == 0:
            return {
                'team_name': normalized_name,
                'year': year,
                'wins_count': 0,
                'games_played': 0,
                'wins': []
            }

        # Compute max total_points per game (across all teams)
        max_points_per_game = all_scores.groupby('game_id')['total_points'].max()

        # Get the team's rows only
        team_scores = all_scores[team_mask].copy()

        # A win: team's total_points == max total_points for that game
        team_scores['game_max'] = team_scores['game_id'].map(max_points_per_game)
        wins_df = team_scores[team_scores['total_points'] == team_scores['game_max']]

        # Build structured win records
        point_columns = [
            'vybor_points', 'chisla_points', 'pref_points', 'pairs_points',
            'razobl_points', 'auction_points', 'mot_points'
        ]
        wins_list = []
        for _, row in wins_df.iterrows():
            win_record = {
                'game_id': int(row['game_id']),
                'game_date': str(row['game_date']),
                'team_name': row['team_name'],
                'total_points': float(row['total_points']),
            }
            for col in point_columns:
                win_record[col] = float(row[col])
            wins_list.append(win_record)

        return {
            'team_name': normalized_name,
            'year': year,
            'wins_count': len(wins_list),
            'games_played': games_played,
            'wins': wins_list
        }

    def execute_custom_query(self, query_description: str, params: Dict[str, Any]) -> pd.DataFrame:
        """
        Execute a custom query based on description and parameters.
        This method interprets common query patterns.

        Args:
            query_description: Description of what to query
            params: Parameters for the query

        Returns:
            DataFrame with query results
        """
        # This is a simplified version - can be extended based on needs
        if 'top' in query_description.lower() and 'team' in query_description.lower():
            limit = params.get('limit', 10)
            return self._get_top_teams(limit)
        elif 'game' in query_description.lower() and 'date' in query_description.lower():
            start_date = params.get('start_date')
            end_date = params.get('end_date')
            if start_date:
                game_ids = self.get_games_by_date_range(start_date, end_date)
                scores = self.get_team_game_scores()
                return scores[scores['game_id'].isin(game_ids)]

        # Default: return all team game scores
        return self.get_team_game_scores()

    def _get_top_teams(self, limit: int = 10) -> pd.DataFrame:
        """Get top teams by total points."""
        df = self.get_team_game_scores()
        if df.empty:
            return df

        team_totals = df.groupby('team_name').agg({
            'total_points': 'sum',
            'game_id': 'count'
        }).rename(columns={'game_id': 'games_played'})

        team_totals = team_totals.sort_values('total_points', ascending=False).head(limit)
        return team_totals.reset_index()
