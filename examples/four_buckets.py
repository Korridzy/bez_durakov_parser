import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from sqlalchemy import and_

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from db import Database, TeamGameScore
from db_helpers import normalize_team_name


def evaluate_four_bucket_strategy(team_name):
    """Calculate team performance data with and without last round"""

    # Connect to database
    db = Database()

    # Normalize team name for database comparison
    normalized_team_name = normalize_team_name(team_name)

    # Get games from the last year
    one_year_ago = datetime.now() - timedelta(days=365)

    with db.Session() as session:
        # Get all games with target team from last year
        games_with_team = session.query(TeamGameScore).filter(
            and_(
                TeamGameScore.game_date >= one_year_ago,
                TeamGameScore.team_name == normalized_team_name
            )
        ).order_by(TeamGameScore.game_date).all()

        dates = []
        places_with_last = []
        places_without_last = []

        for target_team_score in games_with_team:
            game_id = target_team_score.game_id
            game_date = target_team_score.game_date

            # Get all teams for this game
            all_teams = session.query(TeamGameScore).filter(
                TeamGameScore.game_id == game_id
            ).all()

            # Calculate places with all rounds (normal results)
            teams_with_last = []
            for team in all_teams:
                total_score = float(team.total_points or 0)
                teams_with_last.append((team.team_name, total_score))

            # Sort by score descending
            teams_with_last.sort(key=lambda x: x[1], reverse=True)
            place_with_last = next(i + 1 for i, (name, _) in enumerate(teams_with_last)
                                  if name == normalized_team_name)

            # Calculate places without last round (mot)
            teams_without_last = []
            for team in all_teams:
                if team.team_name == normalized_team_name:
                    # For target team - exclude mot points
                    total_score = (
                        float(team.vybor_points or 0) +
                        float(team.chisla_points or 0) +
                        float(team.pref_points or 0) +
                        float(team.pairs_points or 0) +
                        float(team.razobl_points or 0) +
                        float(team.auction_points or 0)
                    )
                else:
                    # For other teams - include all points
                    total_score = float(team.total_points or 0)

                teams_without_last.append((team.team_name, total_score))

            # Sort by score descending
            teams_without_last.sort(key=lambda x: x[1], reverse=True)
            place_without_last = next(i + 1 for i, (name, _) in enumerate(teams_without_last)
                                     if name == normalized_team_name)

            dates.append(game_date)
            places_with_last.append(place_with_last)
            places_without_last.append(place_without_last)

    return dates, places_with_last, places_without_last

def visualize_results(dates, places_with_last, places_without_last, team_name):
    """Create and display visualization of team performance"""

    if not dates:
        print(f"No games found for '{team_name}' in the last year")
        return

    # Calculate difference (positive = better without last round)
    place_differences = [with_last - without_last for with_last, without_last in
                        zip(places_with_last, places_without_last)]

    # Create common x positions
    x_positions = range(len(dates))
    date_labels = [date.strftime('%d.%m') for date in dates]

    # Create subplot layout
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot 1: Difference bar chart
    colors = ['green' if diff > 0 else 'red' if diff < 0 else 'gray'
              for diff in place_differences]

    # Use explicit x positions for bars
    bars = ax1.bar(x_positions, place_differences, color=colors, alpha=0.7, width=0.8)
    ax1.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    ax1.set_ylabel('Разность мест')
    ax1.set_title(f'Выгода от сохранения баллов в последнем раунде - "{team_name}"')
    ax1.grid(True, alpha=0.3)

    # Add value labels on bars
    for i, (bar, diff) in enumerate(zip(bars, place_differences)):
        if diff != 0:
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + (0.1 if diff > 0 else -0.1),
                    f'{diff:+d}', ha='center', va='bottom' if diff > 0 else 'top')

    # Set x-axis for bar chart
    ax1.set_xlim(-0.5, len(dates) - 0.5)
    ax1.set_xticks(x_positions)
    ax1.set_xticklabels(date_labels, rotation=45)

    # Plot 2: Original lines - use same x positions
    ax2.plot(x_positions, places_with_last, 'b-', label='Реальные места',
             linewidth=2, marker='o')
    ax2.plot(x_positions, places_without_last, 'r-', label='Без ставок в последнем раунде',
             linewidth=2, marker='s')
    ax2.set_xlabel('Игры')
    ax2.set_ylabel('Место команды')
    ax2.set_title('Места в играх')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.invert_yaxis()

    # Set x-axis for line chart - same as bar chart
    ax2.set_xlim(-0.5, len(dates) - 0.5)
    ax2.set_xticks(x_positions)
    ax2.set_xticklabels(date_labels, rotation=45)

    plt.tight_layout()

    # Statistics
    positive_games = sum(1 for diff in place_differences if diff > 0)
    negative_games = sum(1 for diff in place_differences if diff < 0)
    zero_games = sum(1 for diff in place_differences if diff == 0)

    print(f"\nАнализ {len(dates)} игр:")
    print(f"Выгодно сохранить баллы: {positive_games} игр ({positive_games/len(dates)*100:.1f}%)")
    print(f"Невыгодно сохранять баллы: {negative_games} игр ({negative_games/len(dates)*100:.1f}%)")
    print(f"Без разницы: {zero_games} игр ({zero_games/len(dates)*100:.1f}%)")

    avg_benefit = sum(place_differences) / len(place_differences)
    print(f"Средняя выгода: {avg_benefit:+.2f} мест")

    # Save and show
    png_filename = '4_bucket_strategy_analysis_on_team.png'
    plt.savefig(png_filename, dpi=300, bbox_inches='tight')
    plt.show()

    print(f"График сохранен как {png_filename}")


if __name__ == "__main__":
    target_team_name = "Суровая реальность"

    dates, places_with_last, places_without_last = evaluate_four_bucket_strategy(target_team_name)
    visualize_results(dates, places_with_last, places_without_last, target_team_name)