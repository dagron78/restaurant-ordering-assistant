"""
Background Task Scheduler for Restaurant Ordering Assistant.

Coordinates scheduled tasks:
- Email monitoring (every 8 hours)
- Weekly vendor scraping (Monday mornings)
"""

import sys
import signal
import logging
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.config import Config
from workers.email_monitor import run_email_check
from workers.web_scraper import run_weekly_scrape


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('scheduler')


def email_job():
    """Wrapper for email check job."""
    logger.info("Starting scheduled email check...")
    try:
        results = run_email_check()
        logger.info(f"Email check complete. Items added: {results.get('items_added', 0)}")
    except Exception as e:
        logger.error(f"Email check failed: {e}")


def scrape_job():
    """Wrapper for scraping job."""
    logger.info("Starting scheduled vendor scrape...")
    try:
        results = run_weekly_scrape()
        logger.info(f"Scrape complete. Items updated: {results.get('total_items', 0)}")
    except Exception as e:
        logger.error(f"Scrape failed: {e}")


def create_scheduler() -> BlockingScheduler:
    """
    Create and configure the scheduler.
    
    Returns:
        Configured BlockingScheduler
    """
    scheduler = BlockingScheduler()
    
    # Email check - every 8 hours
    email_interval = Config.EMAIL_CHECK_INTERVAL
    scheduler.add_job(
        email_job,
        IntervalTrigger(hours=email_interval),
        id='email_monitor',
        name=f'Email Monitor (every {email_interval} hours)',
        replace_existing=True
    )
    logger.info(f"Scheduled email check every {email_interval} hours")
    
    # Weekly scrape - Monday at configured hour
    scrape_day = Config.SCRAPE_DAY  # 0 = Monday
    scrape_hour = Config.SCRAPE_HOUR
    
    # Convert day number to cron day (mon=0 in our config, but cron uses mon-sun)
    cron_days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    cron_day = cron_days[scrape_day]
    
    scheduler.add_job(
        scrape_job,
        CronTrigger(day_of_week=cron_day, hour=scrape_hour, minute=0),
        id='weekly_scrape',
        name=f'Weekly Vendor Scrape ({cron_day.title()} at {scrape_hour}:00)',
        replace_existing=True
    )
    logger.info(f"Scheduled weekly scrape on {cron_day.title()} at {scrape_hour}:00")
    
    return scheduler


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Shutdown signal received. Stopping scheduler...")
    sys.exit(0)


def main():
    """Main entry point for the scheduler."""
    print(f"\n{'='*60}")
    print("🕐 Restaurant Ordering Assistant - Background Scheduler")
    print(f"{'='*60}")
    print(f"\nStarted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create scheduler
    scheduler = create_scheduler()
    
    # Print scheduled jobs
    print("\n📋 Scheduled Jobs:")
    for job in scheduler.get_jobs():
        print(f"   - {job.name}")
        print(f"     Next run: {job.next_run_time}")
    
    print(f"\n{'='*60}")
    print("Scheduler running. Press Ctrl+C to stop.")
    print(f"{'='*60}\n")
    
    # Run initial email check
    print("Running initial email check...")
    email_job()
    
    # Start scheduler
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == '__main__':
    main()
