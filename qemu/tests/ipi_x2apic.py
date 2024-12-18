import os
import re

import aexpect
from virttest import env_process, error_context


def get_re_average(opt, re_str):
    """
    Get the average value which match re string.

    :param opt: string that contains all the information.
    :param re_str: re string used to filter the result.
    """

    values = re.findall(re_str, str(opt))
    vals = 0.0
    for val in values:
        val = float(val)
        vals += val
    return vals / len(values)


@error_context.context_aware
def run(test, params, env):
    """
    Measure overhead of IPI with and without x2apic:
    1) Enable ept if the host supports it.
    2) Boot guest with x2apic cpu flag (at least 2 vcpu).
    3) Check x2apic flag in guest.
    4) Run pipetest script in guest.
    5) Boot guest without x2apic.
    6) Run pipetest script in guest.
    7) Compare the result of step4 and step6.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    smp = params.get("smp")
    if int(smp) < 2:
        params["smp"] = 2
        test.log.warning(
            "This case need at least 2 vcpu, but only 1 specified in"
            " configuration. So change the vcpu to 2."
        )
    vm_name = params.get("main_vm")
    error_context.context("Boot guest with x2apic cpu flag.", test.log.info)
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    check_x2apic_cmd = params.get("check_x2apic_cmd")
    if check_x2apic_cmd:
        error_context.context("Check x2apic flag in guest", test.log.info)
        x2apic_output = session.cmd_output(check_x2apic_cmd).strip()
        x2apic_check_string = params.get("x2apic_check_string").split(",")
        for check_string in x2apic_check_string:
            if check_string.strip() not in x2apic_output:
                msg = "%s is not displayed in output" % check_string
                test.fail(msg)

    pipetest_cmd = params.get("pipetest_cmd")
    if session.cmd_status("test -x %s" % pipetest_cmd):
        file_link = os.path.join(test.virtdir, "scripts/pipetest.c")
        vm.copy_files_to(file_link, "/tmp/pipetest.c")
        build_pipetest_cmd = params.get("build_pipetest_cmd")
        error_context.context("Build pipetest script in guest.", test.log.info)
        session.cmd(build_pipetest_cmd, timeout=180)

    error_context.context("Run pipetest script in guest.", test.log.info)
    try:
        o = session.cmd(pipetest_cmd, timeout=180)
    except aexpect.ShellTimeoutError as e:
        o = e
    re_str = params.get("usec_re_str", r"[0-9]*\.[0-9]+")
    val1 = get_re_average(o, re_str)
    session.close()
    vm.destroy()
    error_context.context("Boot guest without x2apic.", test.log.info)
    params["cpu_model_flags"] += ",-x2apic"
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    if check_x2apic_cmd:
        error_context.context("Check x2apic flag in guest after reboot.", test.log.info)
        x2apic_output = session.cmd_output(check_x2apic_cmd).strip()
        test.log.info(x2apic_output)
        if x2apic_output:
            test.fail("Fail to disable x2apic in guest.")

    error_context.context("Run pipetest script in guest again.", test.log.info)
    try:
        o = session.cmd(pipetest_cmd, timeout=180)
    except aexpect.ShellTimeoutError as e:
        o = e
    val2 = get_re_average(o, re_str)
    error_context.context("Compare the output of pipetest script.", test.log.info)
    if val1 >= val2:
        msg = "Overhead of IPI with x2apic is not smaller than that without"
        msg += " x2apic. pipetest script output with x2apic: %s. " % val1
        msg += "pipetest script output without x2apic: %s" % val2
        test.fail(msg)
    msg = "pipetest script output with x2apic: %s. " % val1
    msg += "pipetest script output without x2apic: %s" % val2
    test.log.info(msg)
    session.close()
