# This plugin obtains compiler flags of each compilation unit and
# executes Frama-C on them. Frama-C can be executed either via Speedy
# or directly through Python plugin. If "USE_SPEEDY" option in the
# execute_framac_speedy_config file is set to "Yes", in that case, we
# execute Frama-C via Speedy otherwise via Python plugin.
#
# When using Speedy, along with Frama-C, Speedy Syntax, and Type checking
# is also executed on the compilation unit. Speedy interprets Frama-C output
# and prints result in a particular format. The plugin uses regex to parse the Speedy
# output and to obtain the file path, line number, function name (if available) and the message.
# If the message is a warning, error or specification violation, it creates a Codesonar warning.
#
# When executing Frama-c via Python plugin, the plugin interprets the Frama-C output and generates
# Codesonar warnings if a warning, error or specification violation is found.
#
# This plugin is created as part of SaTC project.
# Note that Speedy was created as part of a NASA-funded project, for which GrammaTech has SBIR rights.
# Frama-C is a third-party, open source, separately licensed, tool available from http://frama-c.com
#
# In order to execute the plugin properly, you will need:
#   - Frama-C installed on the machine
#   - Updated execute_framac_speedy_config file with all the paths set properly.
#   - SpeedyCore.zip [optional], which includes SpeedyCore.jar and speedy-tpbin.
#                        Zip must be extracted somewhere.
#   - Java 8 or above to run Speedy [optional]
#
#
# To use this plugin, either add the following line in the conf file:
# PLUGINS += /path/to/execute_framac_speedy.py
#
# Or put the plugin into the INSTALL/codesonar/plugins directory and
# give it a name like execute_framac_speedy.plugin.py.
#
# Also set the FOREGROUND option either by adding "-foreground" argument
# in command-line or set it in conf file as:
# FOREGROUND = Yes
#
# Once set up, you will notice new warnings classes.
# This plugin adds four new warning classes:
#    - Specification Violation
#    - Specification Warning
#    - Specification Error
#    - Speedy Error

import shutil
import subprocess
import os
import sys
import re
import json
import tempfile
import inspect
import time
import errno
import cs
import process_wp_output
 
#Current File Directory
FILE_DIR = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))

CONFIG_INFO = {}
SFILE_DICT = {}
DEBUG = False
SRC_DIR = "src"

SPEEDY_PROBLEMLISTENER_WARNING_REGEX = r'((?:\S+)):((?:\[wp\] warning)|(?:\[kernel\] warning)):(.*)'
SPEEDY_PROBLEMLISTENER_ERROR_REGEX = r'((?:\S+)):((?:\[kernel\] user error)|(?:\[kernel\] failure)):(.*)'
SPEEDY_PROBLEMLISTENER_WARNING_PATTERN = re.compile(SPEEDY_PROBLEMLISTENER_WARNING_REGEX)
SPEEDY_PROBLEMLISTENER_ERROR_PATTERN = re.compile(SPEEDY_PROBLEMLISTENER_ERROR_REGEX)

FILE_LINE_INFO_REGEX = r'(\S+):(\d+):'
FILE_LINE_INFO_PATTERN = re.compile(FILE_LINE_INFO_REGEX)

SPEEDY_CHECKER_MESSAGE_REGEX = r'(\S+):(\d+):(\d+)-(\d+):(.*)'
SPEEDY_CHECKER_MESSAGE_PATTERN = re.compile(SPEEDY_CHECKER_MESSAGE_REGEX)

@ cs.project_visitor
def setup(proj):
    get_configuration_info(proj.name())
    # Remove TEMP_DIR if existing
    temp_dir = CONFIG_INFO.get("TEMP_DIR", "")

    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
        turn = 0
        while turn < 3: # try 3 times
            try:
                os.makedirs(temp_dir)
            except OSError:
                time.sleep(5) # Sleep for 5 seconds
                turn = turn+1
                if turn >= 3:
                    raise
                else:
                    continue
            break
    else:
        os.makedirs(temp_dir)
        
    # Make a dictionary of sfiles
    sfile_dict = {}
    project = cs.project.current()
    for sfile in project.sfiles():
        if not CONFIG_INFO["USE_SPEEDY"]:
            sfile_dict[str(hash(sfile)) +".c"] = sfile
        else:
            path = os.path.join(CONFIG_INFO["TEMP_DIR"], SRC_DIR, str(hash(sfile)) +".c")
            sfile_dict[path.replace("\\", "/")] = sfile
    global SFILE_DICT
    SFILE_DICT = sfile_dict

    # make a temp dir to put source files
    os.makedirs(temp_dir+"/"+SRC_DIR)    

# Temporary function to obtain configuration information
def get_configuration_info(proj_name):
    global CONFIG_INFO
    
    # Some default values.
    TEMP_DIR = "temp" 
    FRAMAC_LOC = "frama-c"
    SPEEDY_JAR_LOC = "SpeedyCore.jar"
    JAVA_LOC = "java" # Java is required to execute SPEEDY
    
    
    with open(os.path.join(FILE_DIR, 'execute_framac_speedy_config')) as data_file:    
        CONFIG_INFO = json.load(data_file)
        if DEBUG:
            print CONFIG_INFO
            
        if CONFIG_INFO.get("USE_SPEEDY", "") == "" or CONFIG_INFO.get("USE_SPEEDY", "") == "No":
            CONFIG_INFO["USE_SPEEDY"] = False
        else:
            CONFIG_INFO["USE_SPEEDY"] = True
            
        if CONFIG_INFO.get("TEMP_DIR", "") == "" or CONFIG_INFO.get("TEMP_DIR", "") == "/path/to/temp/dir": 
            CONFIG_INFO["TEMP_DIR"] = os.path.join(TEMP_DIR,proj_name) # setting default value
        else:
            CONFIG_INFO["TEMP_DIR"] = os.path.join(CONFIG_INFO["TEMP_DIR"], proj_name)
        if not isDirectoryWritable(CONFIG_INFO.get("TEMP_DIR", "")):
            print "ERROR: Cannot create or write in temp directory: " + CONFIG_INFO.get("TEMP_DIR", "")
            #TODO: This will just print the error. Should we terminate the execution here?
       
        if CONFIG_INFO.get("FRAMAC_LOC", "") == "" or CONFIG_INFO.get("SPEEDY_JAR_LOC", "") == "/path/to/framac/executable":
            CONFIG_INFO["FRAMAC_LOC"] = FRAMAC_LOC # setting default value i.e. "frama-c", which assume frama-c is in path
        else:
            if not os.path.exists(CONFIG_INFO.get("FRAMAC_LOC", "")):
                print "ERROR: Frama-c executable doesn't exist at location: " + CONFIG_INFO.get("FRAMAC_LOC", "")
        
        # SPEEDY jar and Java location is needed only when running frama-C via Speedy 
        if CONFIG_INFO["USE_SPEEDY"]:
            if CONFIG_INFO.get("SPEEDY_JAR_LOC", "") == "" or CONFIG_INFO.get("SPEEDY_JAR_LOC", "") == "/path/to/SpeedyCore.jar":
                CONFIG_INFO["SPEEDY_JAR_LOC"] = SPEEDY_JAR_LOC # assuming SpeedyCore.jar is in path
            else:
                if not os.path.exists(CONFIG_INFO.get("SPEEDY_JAR_LOC", "")):
                    print "ERROR: Speedy executable doesn't exist at location: " + CONFIG_INFO.get("SPEEDY_JAR_LOC", "")
            
            if CONFIG_INFO.get("JAVA_HOME", "") == "" or CONFIG_INFO.get("JAVA_HOME", "") == "/path/to/java-home":
                CONFIG_INFO["JAVA_LOC"] = JAVA_LOC
            else:
                CONFIG_INFO["JAVA_LOC"] = os.path.join(CONFIG_INFO["JAVA_HOME"], "bin/java")
                if not os.path.exists(CONFIG_INFO.get("JAVA_LOC", "")):
                    CONFIG_INFO["JAVA_LOC"] = os.path.join(CONFIG_INFO["JAVA_HOME"], "bin/java.exe")
                    if not os.path.exists(CONFIG_INFO.get("JAVA_LOC", "")):
                        print "ERROR: Java executable doesn't exist at location: " + CONFIG_INFO.get("JAVA_LOC", "")
    if DEBUG:
        print CONFIG_INFO
     
def isDirectoryWritable(directory):
    if os.path.exists(directory):
        try:
            testfile = tempfile.TemporaryFile(dir=directory)
            testfile.close()
        except OSError as e:
            if e.errno == errno.EACCES: 
                return False
            e.filename = directory
            raise
        return True
    else:
        try:
            os.makedirs(directory)
            shutil.rmtree(directory)
        except:
            return False
        return True
        

@ cs.compunit_visitor
# This function executes Frama-c independent of SPEEDY. Currently we are not processing the Frama-c output in this Plugin
def execute_framac(cu):
    if CONFIG_INFO["USE_SPEEDY"]:
        return
    if cu.is_user() and cs.language.C == cu.get_language():
        generate_temp_filesystem(cu.get_sfileinst())
        flags = cu.effective_compiler_flags()
        temp_dir = CONFIG_INFO["TEMP_DIR"]
        cu_name = str(cu)
        framac_loc = CONFIG_INFO["FRAMAC_LOC"]
        # RUN FRAMA-C 
        working_dir = CONFIG_INFO["TEMP_DIR"]+"/"+ SRC_DIR
        frama_c_flags = ['-wp-rte', '-wp', '-wp-print', '-wp-alt-ergo-opt=-backward-compat', '-wp-out', temp_dir.replace("\\", "/")]
        frama_c_flags.extend(CONFIG_INFO["FRAMAC_WP_FLAGS"])
        framac_cmd = [framac_loc] 
        cmd = []
        cmd.extend(framac_cmd)
        flags_string = ' '.join(flags)
        cpp_command = flags_string+ ' -c -C -E -I.'
        cmd.extend(['-cpp-command', cpp_command.replace("\\", "/")])
        cmd.extend(frama_c_flags)
        cmd.append("./"+str(hash(cu.get_sfileinst().get_sfile())) +".c")
        print "Executing frama-c"
        prod_dict = {}
        for prod in cu.procedures():
            prod_dict[str(prod)] = prod
        
        outputFileName = os.path.join(temp_dir, os.path.basename(cu_name)+".txt")
        outputFile = None
        if DEBUG:
            print outputFileName
        outputFile = open(outputFileName, 'w')
        
        my_env = os.environ.copy()
        
        if not framac_loc == "frama-c":
            #add frama-c directory in path as generally alt-ergo is placed in same directory.
            # if alt-ergo is not found in path, Frama-c throws following Error: Alt-Ergo exits with status [127]
            framac_dir = os.path.dirname(framac_loc)
            if framac_dir:
                my_env["PATH"] = str(framac_dir) +  os.pathsep + my_env["PATH"]
        if DEBUG:
            print cmd
            print my_env
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=working_dir, env=my_env, shell=False)
        process_wp_output.parseResultFromOutput(p, outputFile, SFILE_DICT, prod_dict)
        exitcode = p.wait()
        if exitcode != 0:
            raise Exception('ERROR: Failed to run Frama-c analysis on compilation unit ' + cu_name)
        if outputFile is not None:
            outputFile.close()
            
# In order to fix the problem that we don't know the directory in which a compilation unit was built
# we are making a temporary filesystem. To create this filesystem we are making use of the information 
# that codesonar provides a unique hash code to each sfile. 
# We create a copy all the sfiles included by current comp unit's sfile_instance and sfiles included 
# by included sfile_isntances and so on until all the sfiles used by current compilation unit are created.
# We use sfile's hash code as the name of the sfile when placing them in temp directory and change includes in includer sfiles
# to point to the created sfiles.      
def generate_temp_filesystem(sfile_inst):
    sfile_hash_set = set()
    process_sfile(sfile_hash_set, sfile_inst)
    sys.stdout.flush()
    
def process_sfile(hash_set, sinst):
    if DEBUG:
        print "processing SFile: "
        print str(sinst)
    if sinst.is_system_include():
        if DEBUG:
            print "it is a system file"
        return 
    
    if hash(sinst.get_sfile()) in hash_set:
        if DEBUG:
            print "it is already processed"
        return 
    else:
        hash_set.add(hash(sinst.get_sfile()))
    
    for child in sinst.children_vector():
        process_sfile(hash_set, child)
    
    # read content of the file
    file_content = sinst.read(1, 0, sinst.line_count()+1, 0)
    content_list = file_content.splitlines()
    #print content_list
    
    lines_updated = set()
    
    for child in sinst.children_vector():
        # get the location of child in file
        sf, line = get_parent_and_line(child)
        lines_updated.add(line-1)
        if DEBUG:
            print "current child is: "
            print str(child)
        if not child.is_system_include():
            hash_v = hash(child.get_sfile())            
            l = line-1
            if hash(sf) == hash(sinst.get_sfile()):
                #replace 
                if DEBUG:
                    print ("replacing %s with %s" %(content_list[l], "#include "+str(hash_v)))
                content_list[l] = '#include \"'+str(hash_v)+'.c\"'
            else:
                if DEBUG:
                    print "this should not happen- includer file return to me is %s but I was expecting %s" \
                    %(str(sf), str(sinst.get_sfile()))
        else:
            if DEBUG:
                print "child is system include -- not replacing"
            
    remove_unused_includes(content_list, lines_updated)
    dir = CONFIG_INFO["TEMP_DIR"]+"/"+ SRC_DIR + "/"
    write_to_file(dir + str(hash(sinst.get_sfile()))+".c", content_list)

# It is possible that a #include is not activated (when it guarded) in one or more
# sfile instances. In such case, we can't update that include with its sfile's hash. 
# As a hack, we will just comment this include. This function might update a code like:
# char str[] = "
# #include "foo.c" 
# ; 
# to 
# char str[] = "
# //#include "foo.c" 
# ;
# But I am hoping we won't see such cases a lot. 
def remove_unused_includes(content_list, lines_updated):
    for i in range(0, len(content_list)):
        if i not in lines_updated: 
            line = content_list[i].strip()
            if line.startswith("#"):
                pattern = re.compile(r'#\s*include\s*[\"|<]\S+[\"|>]')
                match = pattern.search(line)
                if match and match.group(0):
                    print "updating content from %s to %s" %(content_list[i], "//"+content_list[i])
                    content_list[i] = "//" +content_list[i] 

def write_to_file(file, content):
    # open file as binary to prevent the usage of \r\n as newline. 
    # frama-c generates incorrect line number in case newline character is \r\n
    thefile = open(file, 'wb')
    if thefile is not None:
        for item in content:
            thefile.write("%s\n" % item)
    
        thefile.close()
    
def get_parent_and_line(sf):
    parent = sf.parent()
    cu, cu_line = sf.line_to_compunit_line(1)
    includer_sf, includer_line = cu.line_to_sfileinst_line(cu_line - 1)
    
    if includer_sf != parent:
        print '%s should be included by %s but it is instead %s' % (sf, parent, includer_sf)
    
    pair = includer_sf.get_sfile(), includer_line
    return pair
    
# For now we are executing Frama-c via SPEEDY because in SPEEDY we have code to process Frama-c output and print required information. 
@ cs.compunit_visitor
def execute_speedy(cu):
    if not CONFIG_INFO["USE_SPEEDY"]:
        return
        
    if cu.is_user() and cs.language.C == cu.get_language():
        generate_temp_filesystem(cu.get_sfileinst())
        flags = cu.effective_compiler_flags()
        cu_name = str(cu)
        
        # Make a dictionary of sfiles and procedures
        #sfile_dict = {}
        prod_dict = {}
        #project = cs.project.current()
        #for sfile in project.sfiles():
        #    sfile_dict[str(sfile).replace("\\", "/")] = sfile
        #TODO: Frama-c allows to define specifications in header files, before a function declaration. 
        #      In that case current implementation will added codesonar warning in header file using procedure 
        #      defined in source file. Is that OK or is it better to leave procedure column empty?         
        #for prod in project.procedures_vector():
        for prod in cu.procedures():
            prod_dict[str(prod)] = prod
            
        # Note: Currently speedy is configured to always use gcc as compiler. 
        #        It might be better to add an option to pass complete -cpp-command to speedy.
        cpp_command = '\"'+' '.join(flags[1:])+ ' -c\"'
        temp_fs_cu = "./"+str(hash(cu.get_sfileinst().get_sfile())) +".c"
        wp_flag = ""
        for s in CONFIG_INFO["FRAMAC_WP_FLAGS"]:
            if " " in s.strip():
                wp_flag = wp_flag + " " + "\'" + s.strip() + "\'"
            else:
                wp_flag = wp_flag + " " + s.strip()                
        wp_flag = wp_flag.strip()
        
        speedy_cmd = [CONFIG_INFO["JAVA_LOC"].replace("\\", "/"), '-jar', CONFIG_INFO["SPEEDY_JAR_LOC"].replace("\\", "/"),
                      '-check', '-framac-wp', '-cppflags', cpp_command, '-output', CONFIG_INFO["TEMP_DIR"]]
        if wp_flag:
            speedy_cmd.extend(['-framac-wp-check-args', "\""+ wp_flag.replace("\"", "'")+"\""])
        
        speedy_cmd.append(temp_fs_cu)
        outputFileName = os.path.join(CONFIG_INFO["TEMP_DIR"], os.path.basename(cu_name)+"_framac.txt")
        outputFile = None
        if DEBUG:
            print outputFileName
            print speedy_cmd
            outputFile = open(outputFileName, 'w')
        
        # TODO: makefile or build command can have code to change directory and then build the project. frama-c or speedy should be
        # executed in the same directory in which project was build as compiler flags are set with respect to that directory. 
        # Is there are way to obtain build directory from codesonar to set cwd?
        working_dir = CONFIG_INFO["TEMP_DIR"]+"/"+ SRC_DIR        
        p = subprocess.Popen(speedy_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=working_dir, shell=False)
        process_speedy_output(p, outputFile, SFILE_DICT, prod_dict)
        exitcode = p.wait()
        if exitcode == 1:
            raise Exception('ERROR: SPEEDY cannot parse the command-line arguments successfully while analysing compilation unit ' + cu_name)
        elif exitcode == 3:
            raise Exception('ERROR: Failed to run Frama-c analysis on compilation unit ' + cu_name) 
        elif exitcode == 4:
            raise Exception('ERROR: SPEEDY internal exception occurred while analysing compilation unit '+ cu_name)
        elif exitcode != 0 and exitcode != 2:
            raise Exception('Unexpected error occurred while executing speedy on compilation unit '+ cu_name)
            
        if outputFile is not None:
            outputFile.close()
        
def process_speedy_output(process, output_file, sfile_dict, prod_dict):
    while True:
        line = process.stdout.readline()
        if line == "":
            break
        if output_file is not None:
            output_file.write(line)
        success = process_commandLine_goal_output(sfile_dict, prod_dict, line)
        if not success:
            success = process_commandline_problemlistener_output(sfile_dict, prod_dict, line)
            if not success and DEBUG:                
                print "Cannot parse line: " + line + " of the output"

def process_commandLine_goal_output(sfile_dict, prod_dict, output):
    data = output.split('(FramacWp)')
    if len(data) == 2:
        results = data[1].strip().split(':')
        if DEBUG:
            print data
            print results
        if len(results) == 2 and results[1].strip().startswith('Satisfied'):
            return True
        else:
            file, line = obtain_file_line_info(data[0])
            if file is not None and line is not None:
                if file in sfile_dict:
                    sf = sfile_dict[file]
                    function_name = ""
                    if len(results[0]) >= len("result for goal for function"): 
                        function_name = results[0][len("result for goal for function"):].strip()
                        
                    procedures = sf.procedures_on_line(int(line))
                    if procedures is not None and len(procedures) > 0:
                        procedure = procedures[0]
                    else:
                        # If the specification is not inside a function definition, in that case procedures will be empty
                        # If it is too bad to create a dictionary of procedures and use it this way, we can leave procedure empty?
                        # This procedure may be defined in a different file, but it seems that for adding warning and filling procedure column it doesn't matter.
                        procedure = prod_dict.get(function_name, None)
                    
                    if procedure:
                        process_wp_output.spec_violation_wc.report(sf.arbitrary_instance(), int(line), procedure, data[1])
                    else:            
                        process_wp_output.spec_violation_wc.report(sf.arbitrary_instance(), int(line), data[1])
                return True
            else:
                return False
    else:
        return False

def obtain_file_line_info(info):
    match = FILE_LINE_INFO_PATTERN.search(info)
    if match is not None:
        file = match.group(1)
        line = match.group(2)
        return file, line
    else:
        return None, None
    
def process_commandline_problemlistener_output(sfile_dict, prod_dict, line):
    warning_class = process_wp_output.spec_warning_wc
    match = SPEEDY_PROBLEMLISTENER_WARNING_PATTERN.search(line)
    if match is None:
        match = SPEEDY_PROBLEMLISTENER_ERROR_PATTERN.search(line)
        warning_class = process_wp_output.spec_error_wc
        
    if match is not None:
        error = match.group(3)
        file_info = match.group(1)
        file, line = obtain_file_line_info(file_info)
        if file is not None and line is not None:
            if file in sfile_dict:
                sf = sfile_dict[file]
                # Obtain procedure from line number and sfile. 
                procedures = sf.procedures_on_line(int(line))
                if procedures is not None and len(procedures) > 0:
                    warning_class.report(sf.arbitrary_instance(), int(line), procedures[0], error)
                else:                            
                    warning_class.report(sf.arbitrary_instance(), int(line), error)
                return True
            else: 
                return False
        
        return False
    else:
        match = SPEEDY_CHECKER_MESSAGE_PATTERN.search(line)
        if match is not None:
            file = match.group(1)
            line = match.group(2)
            error = match.group(5)
            if file is not None and line is not None and error is not None:
                if file in sfile_dict:
                    sf = sfile_dict[file]
                    procedures = sf.procedures_on_line(int(line))

                    if procedures is not None and len(procedures) > 0:
                        process_wp_output.speedy_error_wc.report(sf.arbitrary_instance(), int(line), procedures[0], error)
                    else:                            
                        process_wp_output.speedy_error_wc.report(sf.arbitrary_instance(), int(line), error)
                    return True
                else: 
                    return False
    return False

