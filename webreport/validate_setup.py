"""
Quick validation script to check if all components are correctly set up.
"""
import os
import sys

def check_file(filepath, description):
    """Check if file exists."""
    exists = os.path.isfile(filepath)
    status = "✅" if exists else "❌"
    print(f"{status} {description}: {filepath}")
    return exists

def check_dir(dirpath, description):
    """Check if directory exists."""
    exists = os.path.isdir(dirpath)
    status = "✅" if exists else "❌"
    print(f"{status} {description}: {dirpath}")
    return exists

def main():
    """Run validation checks."""
    print("=" * 80)
    print("🔍 WEBREPORT SYSTEM VALIDATION")
    print("=" * 80)
    print()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    all_checks = []

    # Check directories
    print("📁 Directory Structure:")
    all_checks.append(check_dir(os.path.join(base_dir, "backend"), "Backend directory"))
    all_checks.append(check_dir(os.path.join(base_dir, "frontend"), "Frontend directory"))
    all_checks.append(check_dir(os.path.join(base_dir, "agents"), "Agents directory"))
    all_checks.append(check_dir(os.path.join(base_dir, "services"), "Services directory"))
    print()

    # Check main files
    print("📄 Main Files:")
    all_checks.append(check_file(os.path.join(base_dir, "backend", "api.py"), "Backend API"))
    all_checks.append(check_file(os.path.join(base_dir, "frontend", "app.py"), "Frontend App"))
    all_checks.append(check_file(os.path.join(base_dir, "agents", "report_agents.py"), "Agent System"))
    all_checks.append(check_file(os.path.join(base_dir, "services", "game_data_service.py"), "Data Service"))
    print()

    # Check configuration files
    print("⚙️ Configuration:")
    all_checks.append(check_file(os.path.join(base_dir, "requirements.txt"), "Requirements"))
    all_checks.append(check_file(os.path.join(base_dir, "config.yaml"), "Config YAML"))
    all_checks.append(check_file(os.path.join(base_dir, ".env.example"), "Env Example"))
    print()

    # Check Docker files and tools
    print("🐳 Docker & Tools:")
    all_checks.append(check_file(os.path.join(base_dir, "docker-compose.yml"), "Docker Compose"))
    all_checks.append(check_file(os.path.join(base_dir, "Dockerfile.backend"), "Dockerfile Backend"))
    all_checks.append(check_file(os.path.join(base_dir, "Dockerfile.frontend"), "Dockerfile Frontend"))
    all_checks.append(check_file(os.path.join(base_dir, "Makefile"), "Makefile"))
    all_checks.append(check_file(os.path.join(base_dir, "test_system.py"), "Test Script"))
    all_checks.append(check_file(os.path.join(base_dir, "validate_setup.py"), "Validation Script"))
    print()

    # Check documentation
    print("📖 Documentation:")
    all_checks.append(check_file(os.path.join(base_dir, "README.md"), "README"))
    all_checks.append(check_file(os.path.join(base_dir, "ARCHITECTURE.md"), "Architecture"))
    all_checks.append(check_file(os.path.join(base_dir, "USER_GUIDE.md"), "User Guide"))
    print()

    # Check parent project files
    print("🔗 Parent Project Integration:")
    parent_dir = os.path.dirname(base_dir)
    all_checks.append(check_file(os.path.join(parent_dir, "db.py"), "Database ORM"))
    all_checks.append(check_file(os.path.join(parent_dir, "db_helpers.py"), "Database Helpers"))
    all_checks.append(check_file(os.path.join(parent_dir, "config.py"), "Config Module"))
    all_checks.append(check_file(os.path.join(parent_dir, "config.toml"), "Config TOML"))
    print()

    # Summary
    print("=" * 80)
    total = len(all_checks)
    passed = sum(all_checks)
    failed = total - passed

    print(f"📊 SUMMARY:")
    print(f"   Total checks: {total}")
    print(f"   ✅ Passed: {passed}")
    print(f"   ❌ Failed: {failed}")
    print()

    if failed == 0:
        print("🎉 All checks passed! System is ready to use.")
        print()
        print("Next steps:")
        print("1. Run: make start")
        print("2. Open: http://localhost:8501")
        print("3. View logs: make logs")
        return 0
    else:
        print("⚠️ Some checks failed. Please review the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

