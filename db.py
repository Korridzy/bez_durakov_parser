import os
from sqlalchemy import create_engine, Column, Integer, String, Numeric, Date, ForeignKey, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import datetime

# Base class for all models
Base = declarative_base()

# Define models corresponding to database tables
class Game(Base):
    __tablename__ = 'games'

    game_id = Column(Integer, primary_key=True)
    game_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Define relationships
    teams = relationship("GameTeam", back_populates="game")
    vybor_results = relationship("Vybor", back_populates="game")
    chisla_results = relationship("Chisla", back_populates="game")
    pref_results = relationship("Pref", back_populates="game")
    pairs_results = relationship("Pairs", back_populates="game")
    razobl_results = relationship("Razobl", back_populates="game")
    auction_results = relationship("Auction", back_populates="game")
    mot_results = relationship("Mot", back_populates="game")

class Team(Base):
    __tablename__ = 'teams'

    team_id = Column(Integer, primary_key=True)
    team_name = Column(String(1024), nullable=False, unique=True)

    # Define relationships
    games = relationship("GameTeam", back_populates="team")
    vybor_results = relationship("Vybor", back_populates="team")
    chisla_results = relationship("Chisla", back_populates="team")
    pref_results = relationship("Pref", back_populates="team")
    pairs_results = relationship("Pairs", back_populates="team")
    razobl_results = relationship("Razobl", back_populates="team")
    auction_results = relationship("Auction", back_populates="team")
    mot_results = relationship("Mot", back_populates="team")

class GameTeam(Base):
    __tablename__ = 'game_teams'

    game_id = Column(Integer, ForeignKey('games.game_id'), primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.team_id'), primary_key=True)

    # Define relationships
    game = relationship("Game", back_populates="teams")
    team = relationship("Team", back_populates="games")

class Vybor(Base):
    __tablename__ = 'vybor'

    game_id = Column(Integer, ForeignKey('games.game_id'), primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.team_id'), primary_key=True)
    points = Column(Numeric(10, 2), nullable=False)

    # Define relationships
    game = relationship("Game", back_populates="vybor_results")
    team = relationship("Team", back_populates="vybor_results")

class Chisla(Base):
    __tablename__ = 'chisla'

    game_id = Column(Integer, ForeignKey('games.game_id'), primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.team_id'), primary_key=True)
    task_1 = Column(Numeric(10, 2), nullable=False)
    task_2 = Column(Numeric(10, 2), nullable=False)
    task_3 = Column(Numeric(10, 2), nullable=False)
    task_4 = Column(Numeric(10, 2), nullable=False)
    task_5 = Column(Numeric(10, 2), nullable=False)
    total_sum = Column(Numeric(10, 2), nullable=False)

    # Define relationships
    game = relationship("Game", back_populates="chisla_results")
    team = relationship("Team", back_populates="chisla_results")

class Pref(Base):
    __tablename__ = 'pref'

    game_id = Column(Integer, ForeignKey('games.game_id'), primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.team_id'), primary_key=True)
    task_1 = Column(Numeric(10, 2), nullable=False)
    task_2 = Column(Numeric(10, 2), nullable=False)
    task_3 = Column(Numeric(10, 2), nullable=False)
    task_4 = Column(Numeric(10, 2), nullable=False)
    task_5 = Column(Numeric(10, 2), nullable=False)
    task_6 = Column(Numeric(10, 2), nullable=False)
    task_7 = Column(Numeric(10, 2), nullable=False)
    points = Column(Numeric(10, 2), nullable=False)
    penalty = Column(Numeric(10, 2), nullable=False)
    bonus = Column(Numeric(10, 2), nullable=False)
    total_sum = Column(Numeric(10, 2), nullable=False)

    # Define relationships
    game = relationship("Game", back_populates="pref_results")
    team = relationship("Team", back_populates="pref_results")

class Pairs(Base):
    __tablename__ = 'pairs'

    game_id = Column(Integer, ForeignKey('games.game_id'), primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.team_id'), primary_key=True)
    points = Column(Numeric(10, 2), nullable=False)

    # Define relationships
    game = relationship("Game", back_populates="pairs_results")
    team = relationship("Team", back_populates="pairs_results")

class Razobl(Base):
    __tablename__ = 'razobl'

    game_id = Column(Integer, ForeignKey('games.game_id'), primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.team_id'), primary_key=True)
    task_1 = Column(Numeric(10, 2), nullable=False)
    task_2 = Column(Numeric(10, 2), nullable=False)
    task_3 = Column(Numeric(10, 2), nullable=False)
    task_4 = Column(Numeric(10, 2), nullable=False)
    total_sum = Column(Numeric(10, 2), nullable=False)

    # Define relationships
    game = relationship("Game", back_populates="razobl_results")
    team = relationship("Team", back_populates="razobl_results")

class Auction(Base):
    __tablename__ = 'auction'

    game_id = Column(Integer, ForeignKey('games.game_id'), primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.team_id'), primary_key=True)
    task_1_bid = Column(Numeric(10, 2), nullable=False)
    task_1_points = Column(Numeric(10, 2), nullable=False)
    task_1_rate = Column(Numeric(10, 2), nullable=True)
    task_2_bid = Column(Numeric(10, 2), nullable=False)
    task_2_points = Column(Numeric(10, 2), nullable=False)
    task_2_rate = Column(Numeric(10, 2), nullable=True)
    task_3_bid = Column(Numeric(10, 2), nullable=False)
    task_3_points = Column(Numeric(10, 2), nullable=False)
    task_3_rate = Column(Numeric(10, 2), nullable=True)
    task_4_bid = Column(Numeric(10, 2), nullable=False)
    task_4_points = Column(Numeric(10, 2), nullable=False)
    task_4_rate = Column(Numeric(10, 2), nullable=True)
    total_sum = Column(Numeric(10, 2), nullable=False)

    # Define relationships
    game = relationship("Game", back_populates="auction_results")
    team = relationship("Team", back_populates="auction_results")

class Mot(Base):
    __tablename__ = 'mot'

    game_id = Column(Integer, ForeignKey('games.game_id'), primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.team_id'), primary_key=True)
    task_1 = Column(Numeric(10, 2), nullable=False)
    task_2 = Column(Numeric(10, 2), nullable=False)
    task_3 = Column(Numeric(10, 2), nullable=False)
    total_sum = Column(Numeric(10, 2), nullable=False)

    # Define relationships
    game = relationship("Game", back_populates="mot_results")
    team = relationship("Team", back_populates="mot_results")

class Database:
    def __init__(self, db_url=None):
        # If no db_url is provided, use SQLite with a default file path
        if db_url is None:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bez_durakov.db')
            db_url = f'sqlite:///{db_path}'

        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)

    def create_tables(self):
        """Create all tables in the database."""
        Base.metadata.create_all(self.engine)

    def get_or_create_team(self, session, team_name):
        """Get a team by name or create it if it doesn't exist."""
        team = session.query(Team).filter_by(team_name=team_name).first()
        if not team:
            team = Team(team_name=team_name)
            session.add(team)
            session.flush()  # To get the team_id
        return team

    def add_game_data(self, parsed_data):
        """Add game data from the parsed XLSM file structure."""
        session = self.Session()
        try:
            # Create a new game entry
            game_date = parsed_data['date'].date() if hasattr(parsed_data['date'], 'date') else parsed_data['date']
            game = Game(game_date=game_date)
            session.add(game)
            session.flush()  # To get the game_id

            # Process teams
            for team_name in parsed_data['teams']:
                team = self.get_or_create_team(session, team_name)

                # Add game-team relationship
                game_team = GameTeam(game_id=game.game_id, team_id=team.team_id)
                session.add(game_team)

                # Add Vybor data
                vybor_points = parsed_data['vybor'][team_name]
                vybor = Vybor(
                    game_id=game.game_id,
                    team_id=team.team_id,
                    points=vybor_points
                )
                session.add(vybor)

                # Add Chisla data
                chisla_data = parsed_data['chisla'][team_name]
                chisla = Chisla(
                    game_id=game.game_id,
                    team_id=team.team_id,
                    task_1=chisla_data['I'],
                    task_2=chisla_data['II'],
                    task_3=chisla_data['III'],
                    task_4=chisla_data['IV'],
                    task_5=chisla_data['V'],
                    total_sum=chisla_data['Сумма']
                )
                session.add(chisla)

                # Add Pref data
                pref_data = parsed_data['pref'][team_name]
                pref = Pref(
                    game_id=game.game_id,
                    team_id=team.team_id,
                    task_1=pref_data['I'],
                    task_2=pref_data['II'],
                    task_3=pref_data['III'],
                    task_4=pref_data['IV'],
                    task_5=pref_data['V'],
                    task_6=pref_data['VI'],
                    task_7=pref_data['VII'],
                    points=pref_data['Points'],
                    penalty=pref_data['Penalty'],
                    bonus=pref_data['Bonus'],
                    total_sum=pref_data['Сумма']
                )
                session.add(pref)

                # Add Pairs data
                pairs_points = parsed_data['pairs'][team_name]
                pairs = Pairs(
                    game_id=game.game_id,
                    team_id=team.team_id,
                    points=pairs_points
                )
                session.add(pairs)

                # Add Razobl data
                razobl_data = parsed_data['razobl'][team_name]
                razobl = Razobl(
                    game_id=game.game_id,
                    team_id=team.team_id,
                    task_1=razobl_data['I'],
                    task_2=razobl_data['II'],
                    task_3=razobl_data['III'],
                    task_4=razobl_data['IV'],
                    total_sum=razobl_data['Сумма']
                )
                session.add(razobl)

                # Add Auction data
                auction_data = parsed_data['auction'][team_name]
                auction = Auction(
                    game_id=game.game_id,
                    team_id=team.team_id,
                    task_1_bid=auction_data['I']['bid'],
                    task_1_points=auction_data['I']['points'],
                    task_1_rate=auction_data['I'].get('rate'),
                    task_2_bid=auction_data['II']['bid'],
                    task_2_points=auction_data['II']['points'],
                    task_2_rate=auction_data['II'].get('rate'),
                    task_3_bid=auction_data['III']['bid'],
                    task_3_points=auction_data['III']['points'],
                    task_3_rate=auction_data['III'].get('rate'),
                    task_4_bid=auction_data['IV']['bid'],
                    task_4_points=auction_data['IV']['points'],
                    task_4_rate=auction_data['IV'].get('rate'),
                    total_sum=auction_data['Сумма']
                )
                session.add(auction)

                # Add Mot data
                mot_data = parsed_data['mot'][team_name]
                mot = Mot(
                    game_id=game.game_id,
                    team_id=team.team_id,
                    task_1=mot_data['I'],
                    task_2=mot_data['II'],
                    task_3=mot_data['III'],
                    total_sum=mot_data['Сумма']
                )
                session.add(mot)

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            print(f"Error adding game data: {e}")
            return False
        finally:
            session.close()

    def get_all_games(self):
        """Get all games from the database."""
        session = self.Session()
        try:
            return session.query(Game).all()
        finally:
            session.close()

    def get_game_results(self, game_id):
        """Get all results for a specific game."""
        session = self.Session()
        try:
            game = session.query(Game).filter_by(game_id=game_id).first()
            if not game:
                return None

            results = {
                'game_date': game.game_date,
                'teams': [],
                'vybor': {},
                'chisla': {},
                'pref': {},
                'pairs': {},
                'razobl': {},
                'auction': {},
                'mot': {}
            }

            # Get all teams for this game
            game_teams = session.query(GameTeam).filter_by(game_id=game_id).all()
            for game_team in game_teams:
                team = session.query(Team).filter_by(team_id=game_team.team_id).first()
                results['teams'].append(team.team_name)

                # Get Vybor results
                vybor = session.query(Vybor).filter_by(game_id=game_id, team_id=team.team_id).first()
                if vybor:
                    results['vybor'][team.team_name] = vybor.points

                # Get other results similarly...

            return results
        finally:
            session.close()

# Usage example
if __name__ == "__main__":
    db = Database()
    # Use Alembic instead
    # db.create_tables()

    # Example: Add data from parsed XLSM file
    # parsed_data = parse_xlsm("path/to/file.xlsm")
    # db.add_game_data(parsed_data)

    # Example: Get all games
    # games = db.get_all_games()
    # for game in games:
    #     print(f"Game ID: {game.game_id}, Date: {game.game_date}")