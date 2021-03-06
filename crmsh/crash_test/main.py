import os
import sys
import argparse
import logging
import logging.config
from argparse import RawDescriptionHelpFormatter

from . import check
from . import utils
from . import task
from crmsh import utils as crmshutils


logger = logging.getLogger('cpc')


class Context(object):
    """
    Class to store context attributes
    """
    def __init__(self):
        """
        Initialize attributes
        """
        self.process_name = None
        self.var_dir = None
        self.task_list = []
        self.report_path = None
        self.jsonfile = None
        self.logfile = None
        self.current_case = None

        # set by argparse(functions)
        self.check_conf = None
        self.cluster_check = None
        self.sbd = None
        self.corosync = None
        self.pacemakerd = None
        self.fence_node = None
        self.sp_iptables = None
        self.loop = None

        # set by argument(additional options)
        self.force = None
        self.help = None

    def __setattr__(self, name, value):
        super(Context, self).__setattr__(name, value)


ctx = Context()


LOGGING_CFG = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'file_formatter': {
                'format': '%(asctime)s %(name)s %(levelname)s: %(message)s',
                'datefmt': '%Y/%m/%d %H:%M:%S'
                },
            'stream_formatter': {
                '()': 'crmsh.crash_test.utils.MyLoggingFormatter'
                }
            },
        'handlers': {
            'null': {
                'class': 'logging.NullHandler'
                },
            'file': {
                'class': 'logging.FileHandler',
                'formatter': 'file_formatter'
                },
            'stream': {
                'class': 'logging.StreamHandler',
                'formatter': 'stream_formatter'
                }
            },
        'loggers': {
            'cpc': {
                'handlers': ['null', 'file', 'stream'],
                'propagate': False,
                'level': 'DEBUG'
                }
            }
        }


def kill_process(context):
    """
    Testcase: kill cluster related processes
    --kill-sbd            restarted or fenced
    --kill-sbd -l         fenced
    --kill-corosync       restarted or fenced
    --kill-corosync -l    fenced
    --kill-pacemakerd     restarted
    --kill-pacemakerd -l  blocked by bsc#1111692
    """
    for case in ('sbd', 'corosync', 'pacemakerd'):
        if getattr(context, case):
            if case == 'pacemakerd' and context.loop:
                return #blocked by bsc#1111692
            context.current_case = case
            break
    else:
        return

    task_inst = task.TaskKill(context)
    try:
        task_inst.pre_check()
        task_inst.print_header()
        task_inst.enable_report()
        task_inst.run()
        task_inst.wait()
    except task.TaskError as err:
        task_inst.error(str(err))
        raise crmshutils.TerminateSubCommand


def split_brain(context):
    """
    Testcase: make split brain by blocking corosync ports
    """
    if not context.sp_iptables:
        return

    task_inst = task.TaskSplitBrain(context.force)
    try:
        task_inst.pre_check()
        task_inst.print_header()
        with task_inst.do_block():
            task_inst.run()
            task_inst.wait()
    except task.TaskError as err:
        task_inst.error(str(err))
        raise crmshutils.TerminateSubCommand


def fence_node(context):
    """
    Testcase: fence specific node
    """
    if not context.fence_node:
        return

    task_inst = task.TaskFence(context)
    try:
        task_inst.pre_check()
        task_inst.print_header()
        task_inst.run()
        task_inst.wait()
    except task.TaskError as err:
        task_inst.error(str(err))
        raise crmshutils.TerminateSubCommand


class MyArgParseFormatter(RawDescriptionHelpFormatter):
    def __init__(self, prog):
        super(MyArgParseFormatter, self).__init__(prog, max_help_position=50)


def parse_argument(context):
    """
    Parse argument using argparse
    """
    parser = argparse.ArgumentParser(prog=context.process_name,
                                     description="""
Cluster crash test tool set. It standardizes the steps to simulate
cluster failures and to verify some key configuration before you move
your cluster into production. It is carefully designed with the proper
steps and does not change any configuration to harm the cluster without
the confirmation from users.""",
                                     add_help=False,
                                     formatter_class=MyArgParseFormatter,
                                     epilog='''
Log: {}
Json results: {}
For each --kill-* testcase, report directory: {}'''.format(context.logfile,
                                                           context.jsonfile,
                                                           context.report_path))

    #parser.add_argument('-c', '--check-conf', dest='check_conf', action='store_true',
    #                    help='Validate the configurations')

    group_mutual = parser.add_mutually_exclusive_group()
    group_mutual.add_argument('--kill-sbd', dest='sbd', action='store_true',
                              help='Kill sbd daemon')
    group_mutual.add_argument('--kill-corosync', dest='corosync', action='store_true',
                              help='Kill corosync daemon')
    group_mutual.add_argument('--kill-pacemakerd', dest='pacemakerd', action='store_true',
                              help='Kill pacemakerd daemon')
    group_mutual.add_argument('--fence-node', dest='fence_node', metavar='NODE',
                              help='Fence specific node')
    group_mutual.add_argument('--split-brain-iptables', dest='sp_iptables', action='store_true',
                              help='Make split brain by blocking corosync ports')
    parser.add_argument('-l', '--kill-loop', dest='loop', action='store_true',
                        help='Kill process in loop')

    other_options = parser.add_argument_group('other options')
    other_options.add_argument('-f', '--force', dest='force', action='store_true',
                               help='Force to skip all prompts (Use with caution, the intended fault will be injected to verify the cluster resilence)')
    other_options.add_argument('-h', '--help', dest='help', action='store_true',
                               help='Show this help message and exit')

    args = parser.parse_args()
    if args.help or len(sys.argv) == 1:
        parser.print_help()
        raise crmshutils.TerminateSubCommand

    for arg in vars(args):
        setattr(context, arg, getattr(args, arg))


def setup_logging(context):
    """
    Setupt logging
    """
    LOGGING_CFG['handlers']['file']['filename'] = context.logfile
    logging.config.dictConfig(LOGGING_CFG)


def setup_basic_context(context):
    """
    Setup basic context
    """
    var_dir = "/var/lib/crmsh/{}".format(context.process_name)
    context.var_dir = var_dir
    context.report_path = var_dir
    context.jsonfile = "{}/{}.json".format(var_dir, context.process_name)
    context.logfile = "/var/log/crmsh/{}.log".format(context.process_name)


def run(context):
    """
    Major work flow
    """
    setup_basic_context(context)
    parse_argument(context)
    if not utils.is_root():
        logging.fatal("{} can only be executed as user root!".format(context.process_name))
        raise crmshutils.TerminateSubCommand
    if not os.path.exists(context.var_dir):
        os.makedirs(context.var_dir, exist_ok=True)
    setup_logging(context)

    try:
        check.fix(context)
        check.check(context)
        kill_process(context)
        fence_node(context)
        split_brain(context)

    except KeyboardInterrupt:
        utils.json_dumps()
        raise
