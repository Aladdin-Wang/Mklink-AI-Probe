"""Bounded, journaled exclusive jobs. Disconnect is not cancellation or retry."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import secrets
import time

from fastapi import FastAPI, HTTPException
from starlette.routing import Mount

executing_job = ContextVar('mklink_executing_job', default=None)
PATHS = {'flash': '/api/device/flash', 'erase': '/api/device/erase',
         'erase_sector': '/api/device/erase-sector', 'reset': '/api/device/reset',
         'security': '/api/device/security'}
TERMINAL = {'succeeded', 'failed', 'unknown'}
DEPLOYMENT_PATHS = {'offline_deploy': '/api/offline-download/deploy',
                    'flm_copy': '/api/offline-download/algorithm'}


class RuntimeJobs:
    def __init__(self, control):
        self.control = control
        self.jobs = {}
        self.tasks = set()
        self.path = Path(control.info['jobs_path']) if control.info.get('jobs_path') else None
        if self.path and self.path.exists():
            try:
                rows = json.loads(self.path.read_text(encoding='utf-8'))
                for row in rows[-64:]:
                    if row['state'] not in TERMINAL:
                        row.update(state='unknown', error='Backend interrupted; inspect target before any new operation', finished=time.time())
                    self.jobs[row['job_id']] = row
                self.save()
            except (ValueError, KeyError, TypeError) as exc:
                raise RuntimeError('Cannot read job journal; preserve it for inspection') from exc

    @property
    def active(self):
        return next((j for j in self.jobs.values() if j['state'] not in TERMINAL), None)

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(list(self.jobs.values()), ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.path)

    def submit(self, body):
        action, request_id = body.get('action'), body.get('request_id')
        arguments = body.get('arguments', {})
        if body.get('session_id') is not None:
            self.control.validate_session(body['session_id'])
        if action not in PATHS or not isinstance(arguments, dict) or body.get('confirm') is not True:
            raise HTTPException(422, 'Select flash/erase/erase_sector/reset/security with arguments and confirm=true')
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise HTTPException(422, 'A stable request_id is required; reuse it to query an uncertain submission')
        if action == 'flash':
            from mklink.flash_request import validate_flash_request
            try:
                arguments = validate_flash_request(arguments)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        elif action in ('erase', 'erase_sector'):
            from mklink.native_erase import validate_erase_request
            try:
                arguments = validate_erase_request(arguments, sector=action == 'erase_sector')
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        elif action == 'security':
            from mklink.security_operations import validate_security_request
            try:
                arguments = validate_security_request(arguments)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        elif arguments:
            raise HTTPException(422, 'Unsupported job arguments')
        fingerprint = hashlib.sha256(json.dumps([action, arguments], sort_keys=True).encode()).hexdigest()
        previous = self._previous(request_id, fingerprint)
        if previous:
            return previous
        c = self.control
        c.require_identity()
        if self.active or c.operation_lock.locked() or c.attach_lock.locked() or c.online_job():
            raise HTTPException(409, 'Another operation is active; no job was queued')
        from mklink.remote.dashboards import active_bridge_dashboards
        if active_bridge_dashboards():
            raise HTTPException(409, 'Stop acquisition explicitly before an exclusive job')
        device = c.app.state.mklink_state.get('device')
        if action != 'security' and (not device or not device.connected):
            raise HTTPException(409, 'Connect the bound probe before submitting a job')
        if action == 'security' and self.path is None:
            raise HTTPException(503, 'Security journal unavailable; no operation was started')
        if action == 'flash' or (action == 'security' and arguments['action'] == 'lock'):
            firmware = arguments.get('firmware')
            if not Path(firmware).is_file():
                raise HTTPException(422, 'Firmware file is unavailable')
        job = self._accept(action, request_id, fingerprint)
        task = asyncio.create_task(self.execute(job, dict(arguments)))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job

    def _previous(self, request_id, fingerprint):
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise HTTPException(422, 'A stable request_id is required; reuse it to query an uncertain submission')
        previous = next((j for j in self.jobs.values() if j['request_id'] == request_id), None)
        if previous and previous['fingerprint'] != fingerprint:
            raise HTTPException(409, 'request_id already belongs to a different operation')
        return previous

    async def record_deployment(self, request_id, fingerprint, operation, *, action='offline_deploy'):
        """Journal a deployment inside its existing request/temporary-file lifetime."""
        from mklink.runtime_api import active_operation
        current = active_operation.get()
        c = self.control
        if (not current or current[0] is not c or not c.operation_lock.locked()
                or not c.current_operation
                or action not in DEPLOYMENT_PATHS
                or c.current_operation['path'] != DEPLOYMENT_PATHS[action]):
            raise HTTPException(409, 'Deployment requires shared runtime admission')
        previous = self._previous(request_id, fingerprint)
        if previous:
            return previous
        if self.path is None:
            raise HTTPException(503, 'Deployment journal unavailable; no operation was started')
        if self.active:
            raise HTTPException(409, 'Another exclusive job is active')
        job = self._accept(action, request_id, fingerprint)
        async def recovery(directory):
            # Called on the owning event loop, before the worker modifies the disk.
            previous = job.pop('recovery_directory', None)
            if directory is not None:
                job['recovery_directory'] = str(directory)
            try:
                self.save()
            except OSError:
                job.pop('recovery_directory', None)
                if previous is not None:
                    job['recovery_directory'] = previous
                raise
        await self._execute_operation(job, lambda: operation(recovery))
        return job

    def _accept(self, action, request_id, fingerprint):
        """Persist acceptance after the caller's existing admission boundary."""
        job = {'job_id': secrets.token_hex(16), 'request_id': request_id, 'fingerprint': fingerprint,
               'action': action, 'probe_id': self.control.info.get('probe_id'), 'state': 'running', 'started': time.time(),
               'result': None, 'error': None, 'replay': False}
        previous_jobs = self.jobs.copy()
        while len(self.jobs) >= 64:
            self.jobs.pop(next(iter(self.jobs)))
        self.jobs[job['job_id']] = job
        try:
            self.save()  # Persist acceptance before hardware can run.
        except OSError:
            self.jobs.clear()
            self.jobs.update(previous_jobs)
            raise HTTPException(503, 'Job journal unavailable; no operation was started')
        return job

    def _finish(self, job):
        """Persist a terminal result, retaining unknown on journal failure."""
        job['finished'] = time.time()
        try:
            self.save()
        except OSError:
            job.update(state='unknown', error='Result journal failed; inspect target before proceeding')

    async def execute(self, job, arguments):
        token = executing_job.set(job['job_id'])
        try:
            await self._execute_operation(job, lambda: self.control.invoke('POST', PATHS[job['action']], arguments))
        finally:
            executing_job.reset(token)

    async def _execute_operation(self, job, operation):
        try:
            result = await operation()
            encoded = json.dumps(result, ensure_ascii=False)
            if len(encoded) <= 16384:
                job['result'] = result
            elif job['action'] == 'offline_deploy':
                job['result'] = {key: result[key] for key in ('status', 'model', 'script_name')}
                job['result'].update(files=[], file_count=len(result['files']), truncated=True)
            else:
                job['result'] = {'summary': encoded[:16384], 'truncated': True}
            job['state'] = 'failed' if result.get('success') is False or result.get('status') == 'failed' else 'succeeded'
        except HTTPException as exc:
            job.update(state='failed' if exc.status_code < 500 else 'unknown', error=str(exc.detail)[:2048])
            if (job['action'] in DEPLOYMENT_PATHS and isinstance(exc.detail, dict)
                    and exc.detail.get('code') == 'OFFLINE_RECOVERY_REQUIRED'):
                job['recovery_directory'] = str(exc.detail.get('recovery_directory', ''))[:2048]
        except BaseException as exc:
            job.update(state='unknown', error=str(exc)[:2048] or 'Execution interrupted; result unknown')
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            self._finish(job)


def install_jobs(app, control):
    jobs = control.jobs = RuntimeJobs(control)
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.get('/')
    async def listing():
        return {'jobs': list(reversed(jobs.jobs.values()))}

    @api.post('/', status_code=202)
    async def submit(body: dict):
        return jobs.submit(body)

    @api.get('/{job_id}')
    async def get(job_id: str):
        if job_id not in jobs.jobs:
            raise HTTPException(404, 'Job not retained; never infer failure or retry from this response')
        return jobs.jobs[job_id]

    app.router.routes.insert(0, Mount('/api/runtime/jobs', app=api))
