import re
import sys
import os
import cs

PROVED_GOALS = re.compile(r'\S*Proved goals:\s*(\d+)\s*/\s*(\d+)\s*$')
PROVER_RESULT = re.compile(r'\s*Prover\s*(\S+)\s*returns\s*(\w+)\s*')
GOAL_DESCRIPTION= re.compile(r'\s*Goal\s+(\S+)\s+([^\( ]+)? \(.*')
GOAL_POST_CONDITON_DESCRIPTION = re.compile(r'\s*Goal(?:.*)Post-condition\s+(\(.*)?')
GOAL_PRE_CONDITION_DESCRIPTION = re.compile(r'\s*Goal(?:.*)Pre-condition\s+(\(.*)?')
GOAL_DEF_LOCATION = re.compile(r"\s*Goal((?:[^\S]|\S(?!file))*)\(file\s*(\S+)\s*,\s*line\s*(\d+)\s*\)(?:\s*in '(\S+)')?(.*)$")
CALL_SITE_INFORMATION = re.compile(r'((?:[^\S]|\S(?!file))*)\(file\s*(\S+)\s*,\s*line\s*(\d+)\s*\)(?:[^:]*)?:?\s*$')
GOAL_DEF_ASSIGNS = re.compile(r'\s*Goal Assigns\s')
GOAL_DEF_ASSIGNS_NOTHING = re.compile(r"\s*Goal Assigns(?:\s*for '(\S+)')? nothing (?:in '(\S+)')?")
GOAL_DEF_LOOP_ASSINGS_NOTHING = re.compile(r'\s*Goal Loop assigns nothing\s')
GOAL_DEF_COMPLETENESS_CLAUSE = re.compile(r"\s*Goal (Complete behaviors|Disjoint behaviors)\s*'(\S+)'(?:,\s*'(\S+)')*")
GOAL_DEF_WITHOUT_LOCATION = re.compile(r"\s*Goal((?:[^\s\']|\s)*)(?:'(\S+)')?(?:\s*in '(\S+)'(:? at call [^:]+)?)?(?:[^:]*)?:\s*$")
LEMMA_GOAL = re.compile(r'\s*Lemma\s*(\S+)(?:[^:]*)?:\s*$')

WP_WARNING = re.compile(r'\s*((?:\S)*):(\d+)\s*:\s*((?:\[wp\] warning))\s*:((?:\s|\S)*)$')
KERNEL_ERROR = re.compile(r'\s*((?:\S)*):(\d+)\s*:\s*((?:\[kernel\] user error)|(?:\[kernel\] failure))\s*:((?:\s|\S)*)$')
KERNEL_WARNING =re.compile(r'\s*((?:\S)*):(\d+)\s*:\s*((?:\[kernel\] warning))\s*:((?:\s|\S)*)$') 

# New Warning Class
# TODO: Setting significance to DIAGNOSTIC for now.
spec_violation_wc = cs.analysis.create_warningclass('Specification Violation','', 10.0, cs.warningclass_flags.PADDING,cs.warning_significance.DIAGNOSTIC)
spec_warning_wc = cs.analysis.create_warningclass('Specification Warning', '', 10.0, cs.warningclass_flags.PADDING, cs.warning_significance.DIAGNOSTIC)
spec_error_wc = cs.analysis.create_warningclass('Specification Error','', 10.0, cs.warningclass_flags.PADDING, cs.warning_significance.DIAGNOSTIC)
speedy_error_wc = cs.analysis.create_warningclass('Speedy Error','', 10.0, cs.warningclass_flags.PADDING, cs.warning_significance.DIAGNOSTIC)


class GoalDefinition:
    """ Class to store information about a Frama-c Goal definition """
    
    def __init__ (self, forFunctionName, onLineNumber, inFileWithName, info=""):
        self.forFunctionName = forFunctionName
        self.onLineNumber = onLineNumber
        self.inFileWithName = inFileWithName
        self.info = info
        
    def __repr__(self):
        return 'GoalDefinition(for-funtion=%s, on-line=%d, in-file=%s, info=%s )' \
            % (self.forFunctionName, self.onLineNumber, self.inFileWithName, self.info)

class CallSiteDefintion:
    
    def __init__(self, toFunctionName, fromFunctionName, onLineNumber, inFileWithName, info):
        self.toFunctionName = toFunctionName
        self.fromFunctionName = fromFunctionName
        self.onLineNumber = onLineNumber
        self.inFileWithName = inFileWithName
        self.info = info
        
    def __repr__(self):
        return 'CallSiteDefintion(toFunctionName=%s, fromFunctionName=%s, onLineNumber=%d, inFileWithName=%s, info=%s )' \
            % (self.toFunctionName, self.fromFunctionName, self.onLineNumber, self.inFileWithName, self.info)
    
def parseResultFromOutput(process, output_file, sfile_dict, proc_dict):
    provedGoalsChecksum = None
    totalGoalsChecksum = None
    consumedGoalDefs = 0
    consumedGoalResults =0
    positiveProvedGoals = 0
    negativeProvedGoals = 0
    tool_error = None
    
    while totalGoalsChecksum is None: 
        line = process.stdout.readline()
        if line == "":
            break
        if output_file is not None:
            output_file.write(line)
        
        # Process summary of frama-c Execution
        if "command not found" in line:
            raise Exception(line)
        
        # check for kernel error and WP warnings
        checkForErrorOrWarning(line,sfile_dict, proc_dict)
        
        match = PROVED_GOALS.search(line)
        if match is not None:
            provedGoalsChecksum = int(match.group(1))
            totalGoalsChecksum = int(match.group(2))
            continue
    
    currentFunction = None
    goalTopic = None
    isPreCondition = False
    isPostCondition = False
    parsing_goal_def = None
    call_site_def = None
    while True:
        line = process.stdout.readline()
        if line == "":
            break
        if output_file is not None:
            output_file.write(line)
            
        # WP makes a section for each function        
        if line.strip().startswith("Function"):
            splits = line.strip().split(" ")
            if len(splits) >= 2:
                currentFunction = splits[1]
                
        precondition_m = GOAL_PRE_CONDITION_DESCRIPTION.search(line)
        if precondition_m is not None:
            isPreCondition = True
        else:
            postcondition_m = GOAL_POST_CONDITON_DESCRIPTION.search(line)
            if postcondition_m is not None:
                isPostCondition = True
        
        # try to match to the goal
        goal_desc = GOAL_DESCRIPTION.search(line)
        if goal_desc is not None:
            goalTopic = goal_desc.group(2)
            # check string is None or empty 
            if not goalTopic:
                goalTopic = goal_desc.group(3)
                
        # Find location in code
        goal_def = GOAL_DEF_LOCATION.search(line)
        if goal_def is not None:
            filename = goal_def.group(2)
            function_name = goal_def.group(4).replace("'", "") if goal_def.group(4) is not None else None
            linenumber = goal_def.group(3)
            parsing_goal_def = GoalDefinition(function_name if function_name else currentFunction,
                                              int(linenumber),
                                              filename)
            if goal_def.group(5) is not None:
                call_site = CALL_SITE_INFORMATION.search(goal_def.group(5))
                if call_site is not None:
                    if not goalTopic:
                        goalTopic = call_site.group(1)
                        
                    in_filename = call_site.group(2)
                    
                    info = ""
                    if isPreCondition:     
                        goalTopic =  "Pre-condition " + goalTopic
                        info = "Pre-condition "
                        if parsing_goal_def.forFunctionName is not None and parsing_goal_def.forFunctionName != "" :
                            info = info + "of " + parsing_goal_def.forFunctionName
                    if call_site.group(1) is not None:
                        s = call_site.group(1).split("'")
                        fromFuntion = ""
                        if s[0].strip().endswith("in"):
                            fromFuntion = s[1].strip()
                    call_site_def = CallSiteDefintion(parsing_goal_def.forFunctionName, 
                                                      fromFuntion,
                                                      int(call_site.group(3)),
                                                      in_filename, 
                                                      info)
                    #print (str(call_site_def))
            if not goalTopic:
                goalTopic = goal_def.group(1)
                
            consumedGoalDefs = consumedGoalDefs +1
            continue
        elif GOAL_DEF_ASSIGNS_NOTHING.search(line) is not None:
            goal_def = GOAL_DEF_ASSIGNS_NOTHING.search(line)
            label = "Assigns nothing"
            function_name = currentFunction
            if not function_name:
                function_name = goal_def.group(2)
            # TODO: Assigns nothing goals don't have line number info
            # so can't create goal definition
            consumedGoalDefs = consumedGoalDefs+1
        elif GOAL_DEF_LOOP_ASSINGS_NOTHING.search(line) is not None:
            label = "Loop assigns nothing"
            consumedGoalDefs = consumedGoalDefs +1
        elif GOAL_DEF_COMPLETENESS_CLAUSE.search(line) is not None:
            goal_def = GOAL_DEF_COMPLETENESS_CLAUSE.search(line)
            clauseType = goal_def.group(1)
            groups = goal_def.groupCount()
            first = True
            behaviors = ""
            for i in range(2, groups):
                s = goal_def.group(i)
                if not s:
                    continue
                if first:
                    first = False
                else:
                    behaviors =  behaviors + ", "
                behaviors = behaviors + goal_def.group(i)
            
            label = clauseType + " " + behaviors
            consumedGoalDefs = consumedGoalDefs +1
        elif GOAL_DEF_WITHOUT_LOCATION.search(line) is not None:
            consumedGoalDefs = consumedGoalDefs +1
        elif GOAL_DEF_ASSIGNS.search(line) is not None:
            consumedGoalDefs = consumedGoalDefs +1
        elif LEMMA_GOAL.search(line) is not None:
            consumedGoalDefs = consumedGoalDefs +1
            
        prover_result = PROVER_RESULT.search(line)
        if prover_result is not None:
            consumedGoalResults = consumedGoalResults+1
            # check if wp has thrown any error for the goal
            nextLine  = process.stdout.readline()
            if nextLine is not None:
                if output_file is not None:
                    output_file.write(line)
                goalerror= ""
                if nextLine.strip().startswith("Error:"):
                    goalerror = nextLine.strip()
                    
            proofResult = False
            result = prover_result.group(2)
            if result == "Valid":
                positiveProvedGoals = positiveProvedGoals+1
                proofResult = True
            elif result == "Invalid" or result == "Unknown" or result == "Failed" or result == "Timeout":
                negativeProvedGoals = negativeProvedGoals+1
                goalerror = result
            else:
                msg = "Proof result is not recognized: " + result
                tool_error = Exception(msg)                
            if parsing_goal_def is not None:
                if goalerror and not proofResult:
                    # create codesonar warning
                    goal_info = ""
                    if goalTopic:
                        goal_info = goalTopic.strip()
                    functionName = parsing_goal_def.forFunctionName if parsing_goal_def.forFunctionName else ""
                    create_codesonar_warning(parsing_goal_def.forFunctionName, 
                                             parsing_goal_def.inFileWithName, 
                                             parsing_goal_def.onLineNumber, 
                                             "result for goal for function " + 
                                              functionName +
                                             ": Violated "+  goal_info +" - "+goalerror,
                                             sfile_dict, proc_dict, spec_violation_wc)
                    if call_site_def is not None:
                        create_codesonar_warning(call_site_def.toFunctionName, 
                                                 call_site_def.inFileWithName,
                                                 parsing_goal_def.onLineNumber, 
                                                 "result for goal for function " + 
                                                 call_site_def.toFunctionName +
                                                 ": Violated "+   call_site_def.info.strip() +" - "+goalerror,
                                                 sfile_dict, proc_dict, spec_violation_wc)
                parsing_goal_def = None
                call_site_def = None
                goalTopic = None
                isPreCondition = False
                isPostCondition = False
            if consumedGoalResults != consumedGoalDefs:
                tool_error = Exception("Number of goal definitions and goal proofs does not match!")
                
    if tool_error is not None:
        raise tool_error
    
    if totalGoalsChecksum is None:
        totalGoalsChecksum =0
    if provedGoalsChecksum is None:
        provedGoalsChecksum = 0
    if positiveProvedGoals + negativeProvedGoals !=  totalGoalsChecksum:
        raise Exception("Number of total goals and number of proofs does not match (%d <> %d)!" 
                        % ( positiveProvedGoals + negativeProvedGoals, totalGoalsChecksum))
    
        
def create_codesonar_warning (function, file, line, msg, sfile_dict, proc_dict, warning_class):
    # print ("create warning - %s in file %s " % (msg, file))
    if file is not None and line is not None and msg is not None:
        updated_file = process_framac_format_file(file)
        if updated_file in sfile_dict:
            sf = sfile_dict[updated_file]
            procedures =  sf.procedures_on_line(line)
            if procedures is not None and len(procedures) >0:
                procedure = procedures[0]
            else:
                # If the specification is not inside a function definition, in that case procedures will be empty
                # If it is too bad to create a dictionary of procedures and use it this way, we can leave procedure empty?
                # This procedure may be defined in a different file, but it seems that for adding warning and filling procedure column it doesn't matter.
                procedure =  proc_dict.get(function, None)
                    
            if procedure:
                warning_class.report(sf.arbitrary_instance(), line, procedure, msg)
            else:            
                warning_class.report(sf.arbitrary_instance(), line, msg)
        else:
            print("WARNING: Cannot create codesonar warning class in file %s " % (updated_file))
        
    
def process_framac_format_file (file_path):
    # for few warning frama-c generate output with relative path
    new_path = ""
    if os.path.isfile(file_path):
        new_path = os.path.abspath(file_path)
    elif os.path.isfile(os.path.join(os.getcwd(), file_path)):
        new_path = os.path.abspath(os.path.join(os.getcwd(), file_path))
    
    if new_path:
        return process_framac_posix_format_file(new_path)
    else:
        return process_framac_posix_format_file(file_path)
    
def process_framac_posix_format_file (file_path):
    if sys.platform == "win32":
        if file_path[1] == ':':
            return file_path.replace("\\", "/")
        elif file_path.startswith("c") or file_path.startswith("C"):
            f = file_path[0] + ':'+file_path[1:]
            return f.replace("\\", "/")
    return file_path.replace("\\", "/")
        
def checkForErrorOrWarning(line, sfile_dict, proc_dict):
    if KERNEL_ERROR.search(line) is not None:
        kernel_error = KERNEL_ERROR.search(line)
        file = kernel_error.group(1)
        line = int (kernel_error.group(2))
        create_codesonar_warning(None, file, line,
                                 kernel_error.group(3)+":"+ kernel_error.group(4),
                                 sfile_dict,proc_dict, spec_error_wc)
    elif KERNEL_WARNING.search(line) is not None:
        kernel_warning = KERNEL_WARNING.search(line)
        file = kernel_warning.group(1)
        line = int (kernel_warning.group(2))
        create_codesonar_warning(None, file, line,
                                 kernel_warning.group(3)+":"+ kernel_warning.group(4),
                                 sfile_dict,proc_dict, spec_warning_wc)
    elif WP_WARNING.search(line) is not None:
        wp_warning = WP_WARNING.search(line)
        file = wp_warning.group(1)
        line = int (wp_warning.group(2))
        create_codesonar_warning(None, file, line,
                                 wp_warning.group(3)+":"+ wp_warning.group(4),
                                 sfile_dict,proc_dict, spec_warning_wc)
    