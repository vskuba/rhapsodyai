import time

from redis_queue.redis_queue import redis_queue_get
from source.cronjob.google.google_ping import google_ping


def redis_queue_google_ping():
    q = redis_queue_get('default')
    job = q.enqueue(google_ping)

    while not job.is_finished and not job.is_failed:
        print(f'Job {job.id} is not finished yet\n')
        time.sleep(1)
        job.refresh()

    if job.is_failed:
        return job.latest_result()

    return job.return_value()


if __name__ == '__main__':
    print(f'Redis queue return value: ', redis_queue_google_ping())
