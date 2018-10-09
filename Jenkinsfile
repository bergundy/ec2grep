// vim: filetype=groovy
def base = evaluate(new File('/var/jenkins_home/workspace/Infra/build-scripts/build/Jenkinsfile'))
base.execute([
    customStages: [
        'post-dist': {
            def pkg = base.pypi_build()
            base.pypi_dist_package(pkg)
        }
    ],
    distImages: [],
    allocateNode: true,
    nodeLabel: 'master'
])