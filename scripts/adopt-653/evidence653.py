"""653 correction 2: which attempt's evidence the Windows judge reads for one job of one run attempt.

usage: evidence653.py <run.json> <jobs.json> <artifacts.json> <job name> <artifact prefix or ->

`gh run rerun --failed` re-runs only the failed jobs. The jobs API of the new attempt then lists every job with
run_attempt = the new attempt, but a job that was carried over keeps the started_at of the attempt that ran it, which
is before the new attempt's run_started_at. Its artifact keeps that attempt's suffix (<prefix><attempt>).
Rules:
  - a job that started at or after run_started_at ran in this attempt: only <prefix><this attempt> counts;
  - a job that started before it was carried over: only with conclusion success, and then the artifact of the highest
    earlier attempt that exists (not expired);
  - anything else, or a missing artifact, is NONE (the judge FAILs).
Prints one line: 'ATTEMPT <n> <artifact name or -> | <reason>' or 'NONE - | <reason>'. Read only; exit 0.
"""
import json
import sys


def main(run_file: str, jobs_file: str, artifacts_file: str, name: str, prefix: str) -> None:
    """Print the attempt (and artifact) whose evidence stands for job ``name``."""
    run = json.load(open(run_file, encoding='utf-8'))
    attempt = int(run.get('run_attempt') or 1)
    started = run.get('run_started_at') or ''
    job = next((j for j in json.load(open(jobs_file, encoding='utf-8')).get('jobs', []) if j.get('name') == name), None)
    names = {a.get('name') for a in json.load(open(artifacts_file, encoding='utf-8')).get('artifacts', []) if not a.get('expired')}

    if job is None:
        print(f'NONE - | no job {name} in attempt {attempt}')
        return

    # ISO 8601 UTC strings of the same format compare in time order. No run_started_at: treat the job as re-run.
    ran_here = not started or (job.get('started_at') or '') >= started
    if ran_here:
        want = f'{prefix}{attempt}'
        if prefix == '-':
            print(f'ATTEMPT {attempt} - | ran in attempt {attempt} (started_at {job.get("started_at")} >= run_started_at {started or "unknown"}); judged from the jobs API')
        elif want in names:
            print(f'ATTEMPT {attempt} {want} | ran in attempt {attempt} (started_at {job.get("started_at")} >= run_started_at {started or "unknown"})')
        else:
            print(f'NONE - | ran in attempt {attempt}, but its own artifact {want} is missing (an earlier attempt never stands in for a re-run job)')
        return

    if job.get('conclusion') != 'success':
        print(f'NONE - | carried over from an earlier attempt (started_at {job.get("started_at")} < run_started_at {started}) with conclusion {job.get("conclusion")}, not success')
        return
    if prefix == '-':
        print(f'ATTEMPT {attempt - 1} - | did not run in attempt {attempt} (started_at {job.get("started_at")} < run_started_at {started}); carried over with conclusion success; judged from the jobs API')
        return
    for n in range(attempt - 1, 0, -1):
        if f'{prefix}{n}' in names:
            print(f'ATTEMPT {n} {prefix}{n} | did not run in attempt {attempt} (started_at {job.get("started_at")} < run_started_at {started}); carried over with conclusion success from attempt {n}')
            return
    print(f'NONE - | carried over with conclusion success, but no earlier artifact {prefix}<n> exists')


if __name__ == '__main__':
    main(*sys.argv[1:6])
