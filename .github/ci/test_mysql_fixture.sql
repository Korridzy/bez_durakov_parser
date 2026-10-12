-- CI precondition for webreport/backend/test_system.py (TestGameDataService):
-- test_regression_service_get_team_statistics looks this team up by name, so the row must
-- exist; with no games the service still returns its statistics dictionary.
-- The name is already in normalize_team_name() form (NFC, lowercase, single spaces).
INSERT IGNORE INTO teams (team_name) VALUES ('однажды было дважды');
