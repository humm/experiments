import sys
import collections
import argparse
import subprocess

import scicfg
from clusterjobs import qstat, context, jobgroup

from . import jobs


def parser():
    p = argparse.ArgumentParser(description='configure jobs for experiments')
    p.add_argument('--hd', dest='hd',    default=False, action='store_true', help='write config files to disk')
    p.add_argument('--noqsub', dest='noqsub',    default=False, action='store_true', help='act as if qsub was not available')
    p.add_argument('-v', dest='verbose', default=False, action='store_true', help='display job status')
    p.add_argument('-w', dest='werbose', default=False, action='store_true', help='display job status, without done jobs')
    p.add_argument('-a', dest='analysis', default=False, action='store_true', help='run analysis jobs')
    p.add_argument('-q', dest='quiet',   default=False, action='store_true', help='display only task counts. override verbose and werbose')
    p.add_argument('-t', dest='tmp_res', default=False, action='store_true', help='compute temporary results')
    p.add_argument('-r', dest='result_only', default=False, action='store_true', help='compute only results')
    p.add_argument('--run', dest='run',  default=False, action='store_true', help='launch the necessary commands from python')
    return p.parse_args()


def grp_cmdline(grp, script_name='run.sh', rep_modulo=(1, 0)):
    args = parser()

    if args.noqsub:
        for job in grp.jobs:
            job.context.qsub = False
    if args.hd:
        grp.prepare_hds()
    grp.update_group()

    job_subset = set()
    for job in grp.jobs:
        if (not hasattr(job, 'key')) or job.rep % rep_modulo[0] == rep_modulo[1]:
            job_subset.add(job.name)

    job_torun = set(job.name for job in grp.to_run())
    job_torun = job_torun.intersection(job_subset)

    if args.verbose or args.werbose:
        grp.print_status(done=not args.werbose, quiet=args.quiet, job_subset=job_subset)

    if args.run:
        cmds = grp.run_commands(job_names=job_torun)
        for cmd in cmds:
            print(cmd)
            subprocess.call(cmd, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, shell=True)


def populate_grp(cfg, grp=None):
    ctx = context.Context(cfg.meta.rootpath, cfg.exp.path)
    if grp == None:
        grp = jobgroup.JobBatch(context.Env(user=cfg.meta.user))

    jd = {'setup': [],
          'explorations': [],
          'testsets': {testset_name:[] for testset_name in cfg.testsets._children_keys()},
          'tests':    {test_name:[] for test_name in cfg.tests._children_keys()},
          'results':  {test_name:[] for test_name in cfg.tests._children_keys()}}

    if qstat.qsub_available():
        with open('run.pbs') as f:
            pbs_script = f.read()
        jd['setup'].append(jobs.SetupJob(ctx, (), (cfg, pbs_script), jobgroup=grp))
    for rep in range(cfg.exp.repetitions):
        jd['explorations'].append(jobs.ExplorationJob(ctx, (), (cfg, rep), jobgroup=grp))

    if cfg.meta.run_tests:
        for testsetname in cfg.testsets._children_keys():
            jd['testsets'][testsetname].append(jobs.TestsetJob(ctx, (), (cfg, testsetname), jobgroup=grp))

        for testname in cfg.tests._children_keys():
            for ex_job in jd['explorations']:
                jd['tests'][testname].append(jobs.TestJob(ctx, (), (cfg, ex_job, testname), jobgroup=grp))

            jd['results'][testname].append(jobs.ResultJob(ctx, (), (cfg, testname), jobgroup=grp))

    return jd


def dict_exps(exps, exp_cfgs=None):
    if exp_cfgs is None:
        exp_cfgs = collections.OrderedDict()
    if isinstance(exps, scicfg.SciConfig):
        exp_cfgs[experiments.expkey(exps)] = exps
    else:
        for exp in exps:
            if isinstance(exp, scicfg.SciConfig):
                exp_cfgs[jobs.keys.expkey(exp)] = exp
            else:
                dict_exps(exp, exp_cfgs=exp_cfgs)
    return exp_cfgs


def flatten_exps(exp_cfgs):
    return list(dict_exps(exp_cfgs).values())


def run_exps(cfgs):
    cfgs = flatten_exps(cfgs)
    grp = jobgroup.JobBatch(context.Env(user=cfgs[0].meta.user))

    for cfg in cfgs:
        populate_grp(cfg, grp)

    grp_cmdline(grp)
